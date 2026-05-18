/* =========================================================
   Migración v002 — padrón completo
   Aplica a {{SCHEMA}}.
   - Reemplaza viviendas y moradores (placeholders de v001).
   - Crea vivienda_inventario (effective dating), vivienda_fotos, vivienda_eventos.
   ========================================================= */

DROP TABLE IF EXISTS {{SCHEMA}}.moradores CASCADE;
DROP TABLE IF EXISTS {{SCHEMA}}.viviendas CASCADE;

CREATE TABLE {{SCHEMA}}.viviendas (
    id SERIAL PRIMARY KEY,
    codigo_interno VARCHAR(30) UNIQUE NOT NULL,
    comunidad_id INT NOT NULL REFERENCES {{SCHEMA}}.comunidades(id) ON DELETE RESTRICT,
    referente_id INT REFERENCES {{SCHEMA}}.referentes(id) ON DELETE SET NULL,
    fuente_validacion VARCHAR(80),
    referencia_fisica TEXT NOT NULL,
    direccion_textual VARCHAR(200),
    gps_lat NUMERIC(10, 7),
    gps_lng NUMERIC(10, 7),
    gps_precision_metros INT,
    foto_fachada_url VARCHAR(400),
    estado_servicio VARCHAR(20) NOT NULL DEFAULT 'activo',
    observaciones TEXT,
    empadronada_por_user_id INT NOT NULL,
    empadronada_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actualizada_por_user_id INT,
    actualizada_at TIMESTAMPTZ,
    activa BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX idx_viviendas_comunidad_{{SCHEMA}} ON {{SCHEMA}}.viviendas (comunidad_id);
CREATE INDEX idx_viviendas_estado_{{SCHEMA}} ON {{SCHEMA}}.viviendas (estado_servicio);
CREATE INDEX idx_viviendas_codigo_{{SCHEMA}} ON {{SCHEMA}}.viviendas (codigo_interno);

CREATE TABLE {{SCHEMA}}.moradores (
    id SERIAL PRIMARY KEY,
    vivienda_id INT NOT NULL REFERENCES {{SCHEMA}}.viviendas(id) ON DELETE CASCADE,
    dni VARCHAR(8) NOT NULL,
    nombre_completo VARCHAR(160) NOT NULL,
    fecha_nacimiento DATE,
    sexo VARCHAR(1),
    telefono VARCHAR(20),
    es_jefe_familia BOOLEAN NOT NULL DEFAULT FALSE,
    es_responsable_pago BOOLEAN NOT NULL DEFAULT FALSE,
    dni_foto_url VARCHAR(400),
    acceso_portal BOOLEAN NOT NULL DEFAULT FALSE,
    access_code VARCHAR(120),
    debe_cambiar_clave BOOLEAN NOT NULL DEFAULT TRUE,
    ultimo_login TIMESTAMPTZ,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    UNIQUE (vivienda_id, dni)
);

CREATE INDEX idx_moradores_dni_{{SCHEMA}} ON {{SCHEMA}}.moradores (dni);
CREATE INDEX idx_moradores_vivienda_{{SCHEMA}} ON {{SCHEMA}}.moradores (vivienda_id);

CREATE TABLE {{SCHEMA}}.vivienda_inventario (
    id SERIAL PRIMARY KEY,
    vivienda_id INT NOT NULL REFERENCES {{SCHEMA}}.viviendas(id) ON DELETE CASCADE,
    artefacto_origen VARCHAR(10) NOT NULL,
    artefacto_codigo VARCHAR(30) NOT NULL,
    artefacto_nombre_snapshot VARCHAR(80) NOT NULL,
    cantidad INT NOT NULL DEFAULT 1,
    vigente_desde DATE NOT NULL,
    vigente_hasta DATE,
    motivo_alta VARCHAR(40),
    motivo_baja VARCHAR(40),
    registrado_por_user_id INT NOT NULL,
    dado_de_baja_por_user_id INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (artefacto_origen IN ('catalogo', 'propio')),
    CHECK (cantidad > 0)
);

CREATE INDEX idx_inv_vivienda_vigencia_{{SCHEMA}} ON {{SCHEMA}}.vivienda_inventario (vivienda_id, vigente_hasta);
CREATE INDEX idx_inv_vivienda_codigo_{{SCHEMA}} ON {{SCHEMA}}.vivienda_inventario (vivienda_id, artefacto_codigo);

CREATE TABLE {{SCHEMA}}.vivienda_fotos (
    id SERIAL PRIMARY KEY,
    vivienda_id INT NOT NULL REFERENCES {{SCHEMA}}.viviendas(id) ON DELETE CASCADE,
    url VARCHAR(400) NOT NULL,
    tipo VARCHAR(20) NOT NULL DEFAULT 'fachada',
    tomada_por_user_id INT NOT NULL,
    tomada_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    es_actual BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX idx_fotos_vivienda_{{SCHEMA}} ON {{SCHEMA}}.vivienda_fotos (vivienda_id);

CREATE TABLE {{SCHEMA}}.vivienda_eventos (
    id SERIAL PRIMARY KEY,
    vivienda_id INT NOT NULL REFERENCES {{SCHEMA}}.viviendas(id) ON DELETE CASCADE,
    tipo VARCHAR(40) NOT NULL,
    descripcion TEXT,
    metadata JSONB,
    user_id INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_eventos_vivienda_{{SCHEMA}} ON {{SCHEMA}}.vivienda_eventos (vivienda_id, created_at DESC);
