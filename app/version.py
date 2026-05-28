"""
Versionado semver del proyecto electro.

- APP_VERSION: version actualmente desplegada en el servidor.
- MIN_COMPATIBLE_VERSION: clientes con version menor a esta deben actualizar
  obligatoriamente; el sync engine los bloquea hasta que recarguen y reciban
  el nuevo SW. Bumpear solo cuando un cambio rompa retrocompatibilidad
  (ej.: schema de payload, contrato de endpoint).
- RELEASE_DATE: fecha de release para el modal de changelog.

Convencion:
- Patch (1.0.0 → 1.0.1): fix de bug, sin cambios en API ni schema.
- Minor (1.0.0 → 1.1.0): feature nuevo retrocompatible.
- Major (1.0.0 → 2.0.0): cambio incompatible (bump MIN_COMPATIBLE_VERSION).
"""

APP_VERSION = "1.0.0"
MIN_COMPATIBLE_VERSION = "1.0.0"
RELEASE_DATE = "2026-06-01"
