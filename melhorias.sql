-- PostgreSQL. Validar em homologação e confirmar que o evento_id é global
-- para a fonte atual antes de aplicar. Fazer backup e pausar os importadores.
BEGIN;
SET LOCAL lock_timeout = '5s';
LOCK TABLE precatorio, pagamento IN ACCESS EXCLUSIVE MODE;

-- Evidências do legado. Se houver resultado, guardar uma cópia e reconciliar
-- com a fonte antes de tentar a migração novamente.
SELECT evento_id, array_agg(id ORDER BY id) AS ids
FROM pagamento
GROUP BY evento_id
HAVING count(*) > 1 OR evento_id = '' OR evento_id <> btrim(evento_id);

SELECT id, numero_processo, ente_devedor, valor_face
FROM precatorio
WHERE btrim(numero_processo::text) !~ '^[0-9]{20}$'
   OR btrim(ente_devedor) = '' OR valor_face <= 0 OR valor_face = 'NaN'::numeric;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pagamento GROUP BY evento_id
        HAVING count(*) > 1 OR evento_id = '' OR evento_id <> btrim(evento_id)
    ) OR EXISTS (
        SELECT 1 FROM precatorio
        WHERE btrim(numero_processo::text) !~ '^[0-9]{20}$'
           OR btrim(ente_devedor) = '' OR valor_face <= 0 OR valor_face = 'NaN'::numeric
    ) OR EXISTS (
        SELECT 1 FROM pagamento WHERE valor = 'NaN'::numeric
    ) THEN
        RAISE EXCEPTION 'Legado inconsistente. Reconciliar e auditar os registros antes da migração.';
    END IF;
END;
$$;

CREATE TABLE importacao_lote (
    id           BIGSERIAL PRIMARY KEY,
    fonte        TEXT NOT NULL CHECK (btrim(fonte) <> ''),
    nome_arquivo TEXT NOT NULL CHECK (btrim(nome_arquivo) <> ''),
    sha256       TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    recebido_em  TIMESTAMPTZ NOT NULL DEFAULT now(),
    estado       TEXT NOT NULL DEFAULT 'recebido'
                 CHECK (estado IN ('recebido', 'concluido', 'falhou')),
    UNIQUE (fonte, sha256)
);

ALTER TABLE precatorio
    ALTER COLUMN numero_processo TYPE TEXT USING btrim(numero_processo::text),
    ADD CONSTRAINT precatorio_cnj_canonico CHECK (numero_processo ~ '^[0-9]{20}$'),
    ADD CONSTRAINT precatorio_ente_preenchido CHECK (btrim(ente_devedor) <> ''),
    ADD CONSTRAINT precatorio_face_positivo CHECK (valor_face > 0 AND valor_face <> 'NaN'::numeric);

-- A chave estrangeira precatorio_id e o tipo NUMERIC(15,2) são mantidos.
ALTER TABLE pagamento
    ADD COLUMN atualizado_em TIMESTAMPTZ,
    ADD COLUMN importacao_id BIGINT REFERENCES importacao_lote (id),
    ADD CONSTRAINT pagamento_evento_unico UNIQUE (evento_id),
    ADD CONSTRAINT pagamento_evento_preenchido CHECK (evento_id <> '' AND evento_id = btrim(evento_id)),
    ADD CONSTRAINT pagamento_valor_finito CHECK (valor <> 'NaN'::numeric),
    ADD CONSTRAINT pagamento_origem_rastreavel
        CHECK (atualizado_em IS NOT NULL AND importacao_id IS NOT NULL) NOT VALID;

-- NOT VALID preserva linhas legadas sem inventar timestamp ou proveniência.
-- Após backfill a partir de registros comprovados, executar em outra migração:
-- ALTER TABLE pagamento VALIDATE CONSTRAINT pagamento_origem_rastreavel;
-- ALTER TABLE pagamento ALTER COLUMN atualizado_em SET NOT NULL;
-- ALTER TABLE pagamento ALTER COLUMN importacao_id SET NOT NULL;

CREATE INDEX pagamento_precatorio_id_idx ON pagamento (precatorio_id);
CREATE INDEX pagamento_importacao_id_idx ON pagamento (importacao_id);

CREATE TABLE importacao_registro (
    lote_id         BIGINT NOT NULL REFERENCES importacao_lote (id),
    posicao         INTEGER NOT NULL CHECK (posicao > 0),
    original        JSONB NOT NULL,
    evento_id       TEXT,
    pagamento_id    BIGINT REFERENCES pagamento (id),
    estado          TEXT NOT NULL CHECK (estado IN ('recebido', 'aplicado', 'ignorado', 'pendente')),
    motivo          TEXT,
    PRIMARY KEY (lote_id, posicao),
    CHECK ((estado IN ('recebido', 'aplicado') AND motivo IS NULL)
        OR (estado IN ('ignorado', 'pendente') AND motivo IS NOT NULL))
);

CREATE INDEX importacao_registro_pagamento_id_idx ON importacao_registro (pagamento_id);
CREATE INDEX importacao_registro_pendencias_idx ON importacao_registro (lote_id, posicao)
    WHERE estado = 'pendente';

-- Executar após a validação do lote, inclusive empates entre linhas do mesmo
-- evento. Enviar pendências de lote para p_motivo_pendencia. A função protege
-- a versão vigente contra concorrência com outros lotes ou retries.
CREATE FUNCTION registrar_pagamento_importado(
    p_lote BIGINT, p_posicao INTEGER, p_original JSONB, p_evento TEXT,
    p_cnj TEXT, p_tipo TEXT, p_valor NUMERIC, p_pago_em DATE,
    p_atualizado TIMESTAMPTZ, p_motivo_pendencia TEXT DEFAULT NULL
) RETURNS TEXT
LANGUAGE plpgsql
AS $$
DECLARE
    v_precatorio BIGINT;
    v_pagamento BIGINT;
    v_vigente pagamento%ROWTYPE;
    v_estado TEXT := 'pendente';
    v_motivo TEXT := p_motivo_pendencia;
BEGIN
    INSERT INTO importacao_registro (lote_id, posicao, original, evento_id, estado)
    VALUES (p_lote, p_posicao, p_original, p_evento, 'recebido')
    ON CONFLICT (lote_id, posicao) DO NOTHING;

    IF NOT FOUND THEN
        SELECT estado INTO STRICT v_estado FROM importacao_registro
        WHERE lote_id = p_lote AND posicao = p_posicao;
        RETURN v_estado;
    END IF;

    IF v_motivo IS NULL THEN
        SELECT id INTO v_precatorio FROM precatorio WHERE numero_processo = p_cnj;
        IF v_precatorio IS NULL THEN
            v_motivo := 'Processo sem cadastro conciliado.';
        ELSIF p_tipo IS DISTINCT FROM 'pagamento' THEN
            v_motivo := 'Tipo desconhecido ou estorno a confirmar.';
        ELSIF p_evento IS NULL OR p_evento = '' OR p_evento <> btrim(p_evento)
           OR p_pago_em IS NULL OR NOT isfinite(p_pago_em)
           OR p_atualizado IS NULL OR NOT isfinite(p_atualizado)
           OR p_valor IS NULL OR p_valor <= 0 OR p_valor >= 10000000000000
           OR p_valor <> round(p_valor, 2) THEN
            v_motivo := 'ID, data, timestamp ou valor inválido.';
        END IF;
    END IF;

    IF v_motivo IS NULL THEN
        INSERT INTO pagamento AS vigente (
            precatorio_id, evento_id, tipo, valor, pago_em, atualizado_em, importacao_id
        ) VALUES (
            v_precatorio, p_evento, p_tipo, p_valor, p_pago_em, p_atualizado, p_lote
        )
        ON CONFLICT (evento_id) DO UPDATE
            SET valor = EXCLUDED.valor, atualizado_em = EXCLUDED.atualizado_em,
                importacao_id = EXCLUDED.importacao_id
        WHERE vigente.atualizado_em < EXCLUDED.atualizado_em
          AND vigente.precatorio_id = EXCLUDED.precatorio_id
          AND vigente.tipo = EXCLUDED.tipo AND vigente.pago_em = EXCLUDED.pago_em
        RETURNING id INTO v_pagamento;

        IF FOUND THEN
            v_estado := 'aplicado';
        ELSE
            SELECT * INTO STRICT v_vigente FROM pagamento WHERE evento_id = p_evento;
            v_pagamento := v_vigente.id;
            IF v_vigente.atualizado_em IS NULL THEN
                v_motivo := 'Versão legada sem timestamp de origem.';
            ELSIF v_vigente.precatorio_id <> v_precatorio OR v_vigente.tipo <> p_tipo
               OR v_vigente.pago_em <> p_pago_em THEN
                v_motivo := 'Processo, tipo ou data incompatível com a versão vigente.';
            ELSIF v_vigente.atualizado_em > p_atualizado THEN
                v_estado := 'ignorado';
                v_motivo := 'Versão anterior à versão vigente.';
            ELSIF v_vigente.valor = p_valor THEN
                v_estado := 'ignorado';
                v_motivo := 'Mesmo conteúdo normalizado e mesmo instante.';
            ELSE
                v_motivo := 'Mesmo instante com valor divergente.';
            END IF;
        END IF;
    END IF;

    UPDATE importacao_registro
    SET estado = v_estado, motivo = v_motivo, pagamento_id = v_pagamento
    WHERE lote_id = p_lote AND posicao = p_posicao;
    RETURN v_estado;
END;
$$;

COMMIT;

-- Protocolo do importador:
-- 1. Inserir ou obter o lote pela chave (fonte, sha256), preservando o original.
-- 2. BEGIN, bloquear a linha do lote com SELECT ... FOR UPDATE e pular se concluído.
-- 3. Registrar as linhas em ordem estável de evento e atualizar o estado do lote.
-- 4. COMMIT. Se ocorrer erro, ROLLBACK e registrar a falha em outra transação.
-- 5. Calcular o total a partir dos eventos vigentes. Somar pagamentos brutos só
--    após reconciliar o legado. O total líquido depende da regra de estorno.
