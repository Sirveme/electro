/* =========================================================
   Migración v001 — schema tenant ({{SCHEMA}})
   {{SCHEMA}} es reemplazado por el ejecutor por muni_{ubigeo}
   ========================================================= */

CREATE SCHEMA IF NOT EXISTS {{SCHEMA}};

CREATE TABLE IF NOT EXISTS {{SCHEMA}}.perfiles (
    id SERIAL PRIMARY KEY,
    codigo VARCHAR(40) NOT NULL,
    nombre VARCHAR(80) NOT NULL,
    descripcion VARCHAR(200)
);

CREATE TABLE IF NOT EXISTS {{SCHEMA}}.perfiles_permisos (
    perfil_id INT NOT NULL REFERENCES {{SCHEMA}}.perfiles(id) ON DELETE CASCADE,
    permiso_codigo VARCHAR(80) NOT NULL,
    PRIMARY KEY (perfil_id, permiso_codigo)
);

CREATE TABLE IF NOT EXISTS {{SCHEMA}}.usuarios (
    id SERIAL PRIMARY KEY,
    dni VARCHAR(8) UNIQUE NOT NULL,
    nombre_completo VARCHAR(160) NOT NULL,
    email VARCHAR(120),
    telefono VARCHAR(20),
    access_code VARCHAR(120) NOT NULL,
    perfil_id INT REFERENCES {{SCHEMA}}.perfiles(id) ON DELETE SET NULL,
    debe_cambiar_clave BOOLEAN NOT NULL DEFAULT TRUE,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    ultimo_login TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usuarios_dni_{{SCHEMA}} ON {{SCHEMA}}.usuarios (dni);

CREATE TABLE IF NOT EXISTS {{SCHEMA}}.comunidades (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(120) NOT NULL,
    referente_principal_id INT,
    activa BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS {{SCHEMA}}.referentes (
    id SERIAL PRIMARY KEY,
    nombre_completo VARCHAR(160) NOT NULL,
    cargo VARCHAR(40) NOT NULL,
    dni VARCHAR(8),
    telefono VARCHAR(20),
    foto_url VARCHAR(300),
    activo BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS {{SCHEMA}}.artefacto_config (
    id SERIAL PRIMARY KEY,
    catalogo_id INT NOT NULL,
    tarifa_mensual NUMERIC(10,2) NOT NULL,
    habilitado BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (catalogo_id)
);

CREATE TABLE IF NOT EXISTS {{SCHEMA}}.artefacto_propio (
    id SERIAL PRIMARY KEY,
    codigo VARCHAR(30) NOT NULL,
    nombre VARCHAR(80) NOT NULL,
    categoria VARCHAR(40) NOT NULL,
    tarifa_mensual NUMERIC(10,2) NOT NULL,
    habilitado BOOLEAN NOT NULL DEFAULT TRUE,
    orden INT NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS {{SCHEMA}}.config_municipio (
    clave VARCHAR(60) PRIMARY KEY,
    valor TEXT,
    tipo VARCHAR(20) NOT NULL DEFAULT 'string',
    descripcion VARCHAR(200)
);

/* Placeholders para zClaude-02 (mínimo, se amplían luego) */

CREATE TABLE IF NOT EXISTS {{SCHEMA}}.viviendas (
    id SERIAL PRIMARY KEY,
    codigo_interno VARCHAR(40) UNIQUE,
    comunidad_id INT REFERENCES {{SCHEMA}}.comunidades(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS {{SCHEMA}}.moradores (
    id SERIAL PRIMARY KEY,
    vivienda_id INT REFERENCES {{SCHEMA}}.viviendas(id) ON DELETE CASCADE,
    dni VARCHAR(8),
    nombre_completo VARCHAR(160) NOT NULL,
    es_jefe_familia BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_moradores_vivienda_{{SCHEMA}} ON {{SCHEMA}}.moradores (vivienda_id);
