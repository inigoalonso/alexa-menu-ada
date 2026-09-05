# Menú de Ada - Alexa skill v2

This version fixes Python 3.8 compatibility for Alexa-hosted skills.

## Replace these files in Alexa Developer Console

Under **Code**:

1. Replace `lambda_function.py` with `lambda/lambda_function.py` from this package.
2. Replace `requirements.txt` with `lambda/requirements.txt`.
3. Click **Save** and then **Deploy**.

You do not need to rebuild the interaction model unless you changed it separately.

## Test

In the **Test** tab, with testing enabled for Development:

- `abre menú de Ada`
- `pregunta a menú de Ada qué hay el lunes para comer`
- `pregunta a menú de Ada cuál es el próximo menú`

If the code loads but Skolmat cannot be reached, Alexa should now say:

> La skill funciona, pero no he podido consultar el menú de Skolmat ahora mismo.

If Alexa still returns the generic Skill-response error, open **Code > Logs** and inspect the newest CloudWatch log entry. The first red `ERROR` or `Traceback` line identifies the remaining import/deployment problem.
