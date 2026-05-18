/* =========================================================
   Migración v001 — schema public
   Crea el cimiento del SaaS multi-tenant:
   - municipios + suscripciones
   - superadmin_users
   - artefacto_catalogo (maestro)
   - permisos + perfiles plantilla
   - schema_versions (lo crea el ejecutor antes)
   ========================================================= */

CREATE TABLE IF NOT EXISTS public.municipios (
    id SERIAL PRIMARY KEY,
    ubigeo VARCHAR(6) UNIQUE NOT NULL,
    nombre VARCHAR(120) NOT NULL,
    departamento VARCHAR(60),
    provincia VARCHAR(60),
    distrito VARCHAR(60),
    schema_name VARCHAR(20) UNIQUE NOT NULL,
    responsable_nombre VARCHAR(120),
    responsable_dni VARCHAR(8),
    responsable_telefono VARCHAR(20),
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by INT
);

CREATE INDEX IF NOT EXISTS idx_municipios_ubigeo ON public.municipios (ubigeo);
CREATE INDEX IF NOT EXISTS idx_municipios_activo ON public.municipios (activo);

CREATE TABLE IF NOT EXISTS public.suscripciones (
    id SERIAL PRIMARY KEY,
    municipio_id INT NOT NULL REFERENCES public.municipios(id) ON DELETE CASCADE,
    plan VARCHAR(20) NOT NULL DEFAULT 'demo',
    vigente_desde DATE NOT NULL,
    vigente_hasta DATE,
    precio_mensual NUMERIC(10,2),
    activa BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_suscripciones_municipio ON public.suscripciones (municipio_id);

CREATE TABLE IF NOT EXISTS public.superadmin_users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(40) UNIQUE NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    nombre VARCHAR(120) NOT NULL,
    access_code VARCHAR(120) NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.artefacto_catalogo (
    id SERIAL PRIMARY KEY,
    codigo VARCHAR(30) UNIQUE NOT NULL,
    nombre VARCHAR(80) NOT NULL,
    categoria VARCHAR(40) NOT NULL,
    icono VARCHAR(40),
    descripcion TEXT,
    tarifa_sugerida NUMERIC(10,2),
    activo_default BOOLEAN NOT NULL DEFAULT TRUE,
    orden INT NOT NULL DEFAULT 100
);

CREATE INDEX IF NOT EXISTS idx_artefacto_catalogo_categoria ON public.artefacto_catalogo (categoria);

CREATE TABLE IF NOT EXISTS public.permisos (
    id SERIAL PRIMARY KEY,
    codigo VARCHAR(80) UNIQUE NOT NULL,
    modulo VARCHAR(40) NOT NULL,
    opcion VARCHAR(40) NOT NULL,
    accion VARCHAR(40) NOT NULL,
    descripcion VARCHAR(200)
);

CREATE INDEX IF NOT EXISTS idx_permisos_modulo ON public.permisos (modulo);

CREATE TABLE IF NOT EXISTS public.perfiles_plantilla (
    id SERIAL PRIMARY KEY,
    codigo VARCHAR(40) UNIQUE NOT NULL,
    nombre VARCHAR(80) NOT NULL,
    descripcion VARCHAR(200),
    orden INT NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS public.perfiles_plantilla_permisos (
    perfil_id INT NOT NULL REFERENCES public.perfiles_plantilla(id) ON DELETE CASCADE,
    permiso_id INT NOT NULL REFERENCES public.permisos(id) ON DELETE CASCADE,
    PRIMARY KEY (perfil_id, permiso_id)
);
