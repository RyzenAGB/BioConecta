# Guion de Pitch — BioConecta (Duración objetivo: 4 min 30 s)

> **Cómo presentar:**
> 1. Abre en tu navegador [pitch_bioconecta.html](pitch_bioconecta.html) (pulsa **`F`** para pantalla completa, **`← / →`** para avanzar y **`N`** si quieres ver las notas rápidas en pantalla).
> 2. Ten abierta en otra pestaña la app en vivo en **`https://bioconecta.streamlit.app/`** (o da clic al botón verde / escanea el QR de la Slide 7).

---

## Slide 1 — Portada (`0:00 – 0:20`, 20 s)
> *"Buenos días/tardes. Somos el equipo de **BioConecta**, una plataforma geoespacial que utiliza imágenes satelitales abiertas para responder tres preguntas críticas en el norte de Quintana Roo: **dónde puede vivir el jaguar hoy, por dónde necesita desplazarse y qué fragmentos de selva están en riesgo crítico ahora mismo**."*

---

## Slide 2 — El Problema (`0:20 – 0:55`, 35 s)
> *"Seguramente recuerdan los videos virales de 2024 en Cancún: jaguares caminando sobre bardas y patios en **Villas del Mar**, **Fraccionamiento Alôja** y **Av. Arco Norte**. Y dos años antes, en 2022, una cría de jaguar fue atropellada sobre esa misma avenida frente a la UPQROO."*
>
> *"La realidad es clara: **el jaguar no está invadiendo la ciudad; la expansión urbana y vial está fragmentando su selva en islas cada vez más pequeñas**. El problema es que hoy los mapas oficiales tardan años en actualizarse, requieren software GIS especializado y no generan alertas tempranas para saber dónde intervenir antes de que un corredor se cierre por completo."*

---

## Slide 3 — Justificación (`0:55 – 1:25`, 30 s)
> *"Elegimos al **jaguar (*Panthera onca*)** porque está en Peligro de Extinción bajo la NOM-059 y es una **especie paraguas**: de acuerdo con telemetría en la península de Yucatán, necesita al menos **3,600 hectáreas** continuas. Si conservamos sus corredores, protegemos a todo el ecosistema —mono araña, coatí, manglar y acuífero."*
>
> *"Elegimos la zona piloto **UNICARIBE – Rancho Viejo – Zona Continental de Isla Mujeres** (`48,461 ha`) porque es el laboratorio vivo donde chocan el crecimiento de Cancún Norte, el macizo de selva y el Área Natural Protegida Sistema Lagunar Chacmuchuch. Y lo construimos 100% con **datos abiertos** —Sentinel-2, ESA WorldCover, OpenStreetMap y GBIF— con costo cero de licencias."*

---

## Slide 4 — La Solución y Metodología (`1:25 – 1:55`, 30 s)
> *"Para resolverlo diseñamos **BioConecta** siguiendo una metodología híbrida de 5 fases inspirada en CRISP-DM y ecología del paisaje. Primero traducimos la literatura biológica del jaguar en reglas cuantitativas; homologamos todas las capas a una cuadrícula exacta de **30×30 metros** en UTM 16N; modelamos idoneidad de hábitat y rutas de menor costo; corremos un motor de alertas explicables con Sentinel-2 de **2024 a 2026**; y lo servimos en una aplicación web ligera que cualquiera puede usar sin instalar QGIS."*

---

## Slide 5 — Qué hace: Hábitat y Corredores (`1:55 – 2:25`, 30 s)
> *"En la **Vista 1** calculamos la idoneidad de 0 a 1 combinando cobertura vegetal, NDVI reciente de 2026, distancia a carreteras por jerarquía, distancia urbana y cercanía al agua incluyendo cenotes. Además, aplicamos un filtro ecológico que excluye lotes baldíos urbanos y la franja hotelera de Costa Mujeres, dejando **24,007 hectáreas** de hábitat núcleo real."*
>
> *"En la **Vista 2** extraemos los **19 parches núcleo** y aplicamos Dijkstra geométrico sobre una superficie de resistencia híbrida para trazar **28 corredores** y franjas estilo Linkage Mapper, revelando cuellos de botella críticos como el paso de **Rancho Viejo**."*

---

## Slide 6 — Qué hace: Motor de Alertas Tempranas (`2:25 – 2:55`, 30 s)
> *"En la **Vista 3** está nuestro diferenciador clave: el motor de alertas explicables. Comparamos cada parche contra dos umbrales: su pérdida real de vegetación medida con Sentinel-2 entre **2024 y 2026**, y su tamaño frente a las **3,600 hectáreas** del home range."*
>
> *"¿Qué detectó el satélite? Primero, **18 de 19 fragmentos** están por debajo del 50% del home range, demostrando que sin corredores no son viables. Y segundo, **5 parches muestran pérdida activa fuerte justo en la frontera Rancho Viejo – Ciudad Mujeres**: P10 perdió **14.8%**, P03 **13.4%** (más de 31 hectáreas) y P12 **11.7%** en solo dos años."*

---

## Slide 7 — Demo en Vivo de la App (`2:55 – 4:15`, 1 min 20 s)
*(Haz clic en el botón verde o abre **`https://bioconecta.streamlit.app/`**; los jueces también pueden escanear el QR)*

1. **Pestaña 1 — Idoneidad (`20 s`):**
   - Señala el mapa a ancho completo (ciudad y zona hotelera limpias sin ruido).
   - Señala los **8 marcadores**: los naranjas oficiales en selva profunda (`P01`) y el atropellamiento 🚨 + incursiones 🟣 justo en **Av. Arco Norte**.
   - Abre **`⚙️ Ajustes avanzados`**, mueve un slider (ej. *Distancia a carreteras*) y muestra cómo el mapa y las hectáreas se recalculan en vivo en milisegundos.
2. **Pestaña 2 — Conectividad (`20 s`):**
   - Pasa el cursor sobre **`P01`** (`21,363 ha`) y **`P02`** (`1,455 ha`) y señala la franja magenta brillante en **Rancho Viejo**: *"Ese es el cuello de botella prioritario a proteger."*
3. **Pestaña 3 — Umbrales y Alertas (`30 s`):**
   - Cambia el selector superior a **"Solo pérdida de vegetación NDVI (2024→2026)"** para que resalten en rojo **`P10`**, **`P03`** y **`P12`**.
   - **Haz clic sobre `P03`** en el mapa → señala a la derecha su **ficha explicable**: la gráfica de caída `235 → 212 → 204 ha`, el porcentaje del *home range* y el texto exacto del motivo.
4. **Pestaña 4 — Validación (`10 s`):**
   - Muestra brevemente el **`86.4%`** de presencias reales dentro del hábitat núcleo.

---

## Slide 8 — Validación, Escalabilidad y Cierre (`4:15 – 4:45`, 30 s)
> *"Para validar científicamente el modelo lo probamos a escala regional con registros independientes de GBIF e iNaturalist: **el 86.4% de los avistamientos reales de jaguar cae dentro de nuestro hábitat núcleo predicho**, con una idoneidad mediana de **0.90**."*
>
> *"Como nuestra arquitectura separa las reglas biológicas en un solo archivo, BioConecta puede escalarse en días a otras especies como **mono araña** y **coatí**, o automatizarse cada trimestre para apoyar la planeación territorial en Quintana Roo. Todo el código y los datos ya son públicos en GitHub. Muchas gracias, quedamos atentos a sus preguntas."*

---

## Preguntas frecuentes del jurado (respuestas cortas y sólidas)

1. **¿Por qué el ROC-AUC regional salió 0.53 si el 86.4% cae en el núcleo?**
   > *"Porque en el recuadro regional del norte de Q. Roo (que llega hasta El Edén), el 82% del territorio terrestre sigue siendo selva apta; cuando el fondo ya es mayoritariamente hábitat bueno, la curva ROC contra puntos aleatorios se comprime aunque el modelo acierte en el 86.4% de las presencias reales (mediana H = 0.90). Además, algunos registros ciudadanos de iNaturalist tienen coordenadas difuminadas por ser especie protegida."*
2. **¿No es antiguo ESA WorldCover 2021?**
   > *"Sí, por eso no lo usamos para medir deforestación ni para zonas nuevas. Lo complementamos con **330 polígonos actualizados de OpenStreetMap (2026)** para hoteles y desarrollos recientes, y con **Sentinel-2 NDVI de marzo–mayo 2024, 2025 y 2026** para medir el vigor actual y la pérdida reciente de vegetación."*
3. **¿Cómo evitan que la app web se trabe en tiempo real?**
   > *"El cálculo pesado (Dijkstra geométrico y Sentinel-2) se ejecuta offline en Python y genera GeoJSON y rásteres ligeros. En la web solo recalculamos en vivo la suma ponderada de los 5 sliders en NumPy, lo que toma menos de 50 milisegundos."*
4. **¿Cómo se aplica esto en la vida real?**
   > *"Ayuda a municipios, IBANQROO o desarrolladores a priorizar dónde colocar pasos de fauna sobre avenidas como Arco Norte, qué predios de Rancho Viejo conservar para no cortar el corredor entre P01 y P02, y detectar desmontes recientes antes de que se consoliden."*
