# Menú de Ada - Alexa skill

A private Alexa Custom Skill that reads Ada's school menu from Skolmat.info.

## What it does

- `Alexa, abre menú de Ada` -> today's menu
- `Alexa, pregunta a menú de Ada qué hay mañana para comer` -> tomorrow's menu
- `Alexa, pregunta a menú de Ada qué hay el lunes para comer` -> a specific date
- `Alexa, pregunta a menú de Ada cuál es el próximo menú` -> next published school menu

The school identifier is already configured from this feed:

`https://www.skolmat.info/api/public/matsedlar/cmruev9zs000z04jm7oqrub01/rss?limit=7`

The code deliberately uses the JSON endpoint behind the feed instead of parsing RSS.

## Setup in Alexa Developer Console

1. Sign in at the Alexa Developer Console with the same Amazon account used by the Echo.
2. Create a new skill.
3. Name: `Menú de Ada`.
4. Primary locale: `Spanish (ES)` / `es-ES`.
5. Model: `Custom`.
6. Hosting: `Alexa-hosted (Python)`.
7. Create the skill from scratch.
8. Build > Interaction Model > JSON Editor: replace the content with `skill-package/interactionModels/custom/es-ES.json`.
9. Save Model, then Build Model.
10. Code: replace the generated Python handler with `lambda/lambda_function.py`.
11. Replace `requirements.txt` with `lambda/requirements.txt`.
12. Save and Deploy.
13. Test tab: set testing to `Development`.
14. In the simulator, try `abre menú de Ada` or `pregunta a menú de Ada cuál es el próximo menú`.

## Use the exact natural phrase with an Alexa Routine

Because LaunchRequest already returns today's menu, create an Alexa routine:

- When: Voice -> `qué hay hoy para comer en el colegio`
- Action: Skills -> Your Skills -> Menú de Ada -> Open Menú de Ada

Then you can simply say:

`Alexa, ¿qué hay hoy para comer en el colegio?`

and the routine launches the skill, which immediately reads today's menu.

## Important Saturday test

If you install this on a weekend, `abre menú de Ada` correctly says there is no menu for today. Use `cuál es el próximo menú` to verify the connection against the next published school day.

## Language note

The response framing is Spanish, but menu dish names are spoken exactly as Skolmat publishes them, normally in Swedish. Alexa's Spanish text-to-speech does not currently provide a Swedish `sv-SE` SSML language mode, so Swedish pronunciation can sound Spanish-accented.
