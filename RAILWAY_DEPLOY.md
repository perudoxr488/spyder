**Railway**

Usa dos servicios desde el mismo repo:

1. `web`
   Comando:
   ```bash
   gunicorn -w 2 -b 0.0.0.0:$PORT app:app
   ```

2. `worker`
   Comando:
   ```bash
   python main.py
   ```

**Variables recomendadas**

Pon estas variables en ambos servicios:

```text
SPIDERSYN_INTERNAL_API_KEY=pon_un_secret_largo
PANEL_SECRET=pon_otro_secret_largo
PANEL_USER=admin
PANEL_PASSWORD=una_clave_larga
PANEL_PUBLIC=true
ADMIN_ID=tu_id_de_telegram
TOKEN_BOT=tu_token_del_bot
```

Si usas SQLite en Railway, crea un Volume y monta el servicio en una ruta fija. Luego agrega:

```text
SPIDERSYN_DATA_DIR=/data
```

Con esa variable, las bases `multiplataforma.db`, `historial.db`, `compras.db`, `keys.db` y `requests.db` se guardan en `/data`.

Solo en `web`:

```text
PORT=Railway lo asigna solo
```

Solo en `worker`:

```text
API_BASE=https://tu-servicio-web.up.railway.app
```

**Notas**

- `API_BASE` del worker debe apuntar al dominio público del servicio `web`.
- Para no perder SQLite en redeploy, `SPIDERSYN_DATA_DIR` debe apuntar a un Railway Volume.
- Si `web` y `worker` corren separados, SQLite no es ideal para datos compartidos entre ambos servicios. Para producción estable, migra a PostgreSQL/MySQL o mueve las escrituras del worker a endpoints del `web`.
- No dependas de `config.json` en producción para secretos.
- Si mantienes `config.json`, úsalo solo como respaldo local.
- Si activas `PANEL_PUBLIC=true`, el panel quedará accesible por web pero protegido por login.

**Orden sugerido**

1. Crear servicio `web`
2. Crear servicio `worker`
3. Configurar variables
4. Deploy del `web`
5. Copiar URL pública del `web`
6. Pegar esa URL en `API_BASE` del `worker`
7. Deploy del `worker`

**Chequeo rápido**

- `web`: abre `/` y `/admin/login`
- `worker`: revisa logs hasta ver que inició polling
- prueba `/start`, `/me` y el panel
