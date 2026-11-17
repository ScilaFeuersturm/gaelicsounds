# Soltura · textos para generar audios

Exportado el 17/11/2026 desde los cursos A1 y A2 existentes. Se mantiene intacta la guía de backend que ya estaba en la carpeta superior.

## Listados por idioma

### Galés · `cy` · `gales-cy`

- **70 textos principales**: 4 palabras aisladas y 66 frases o secuencias. 1150 caracteres, sin contar separadores.
- **8 textos complementarios**: respuestas modelo de prácticas de escritura. Opcionales para la primera integración.

### Gaélico escocés · `gd` · `gaelico-escoces-gd`

- **72 textos principales**: 4 palabras aisladas y 68 frases o secuencias. 1347 caracteres, sin contar separadores.
- **8 textos complementarios**: respuestas modelo de prácticas de escritura. Opcionales para la primera integración.

## Qué archivo usar

- `01-textos-necesarios.txt`: un texto por línea, sin traducciones ni encabezados. Es el listado principal para generar audio.
- `02-practicas-complementarias.txt`: textos más largos, para una segunda tanda opcional.
- `listado-con-contexto.csv`: texto, traducción disponible, A1/A2, prioridad y referencias al curso. Pensado para revisar con la docente.
- `manifest-audios.json`: los mismos textos con identificadores estables, código de idioma, locale y todas sus ubicaciones. Sirve para asociar cada audio con Soltura. Los campos no presuponen el contrato de tu backend.

## Criterios importantes

- No se repiten textos idénticos entre niveles o secciones. Se conservan diferencias gramaticales: Cymru, Gymru y Nghymru no se fusionan.
- Se conservan tildes, circunflejos, apóstrofos y signos de pregunta. Guardar y enviar como UTF-8; no quitar las marcas de Gàidhlig, tŷ o dhà.
- Generar cada frase completa: no armarla pegando grabaciones de palabras sueltas.
- Algunas líneas son secuencias de números tal como se enseñan, por ejemplo «un, dau, tri». Son un solo texto para pronunciar con pausas.
- `cy` es galés; `gd` es gaélico escocés, no irlandés ni scots. Los locales sugeridos son cy-GB y gd-GB; comprobar el identificador que usa el motor elegido.
- Los listados cubren todos los ejemplos de las lecciones, referencias, vocabulario, frases y palabra del día. No incluyen consignas/explicaciones en español ni fragmentos de respuestas de completar (por ejemplo, una tilde aislada).
- La docente todavía debe validar contenido, pronunciación y variedad. Estos listados no implican que los audios estén generados ni que el curso esté aprobado.
- Conservar el proveedor/modelo/voz, licencia y versión de cada audio generado para poder revisarlo y reemplazarlo.
