# Implantação do FlowTrace

Esta é a estrutura recomendada nas anotações de 17/11/2026:

```
[Roteador do cliente] --NetFlow v9/UDP (rede do cliente)--> [Coletor de borda]
        --rsync/SSH a cada 5 min (cifrado, chave exclusiva)--> [Servidor central /dados]
        --cópia diária--> [S3 São Paulo, Object Lock, 13 meses]
```

- `deploy/coletor/`: kit do coletor de borda e o roteiro do Cisco.
- `deploy/central/`: os serviços do servidor central (gunicorn, Caddy, rotinas e backup).

---

## 1. Servidor central (Debian 12)

VM no Brasil com 2 vCPU e 4–8 GB de RAM, mais um **volume de dados separado** montado em `/dados`.

```sh
apt install -y python3-venv postgresql caddy nfdump rsync rclone git fail2ban unattended-upgrades
systemctl disable --now nfdump.service      # o central só lê; quem grava é o rsync

# Usuários: "flowtrace" roda a aplicação; "coleta" só recebe arquivos dos coletores.
useradd --system --create-home --home-dir /srv/flowtrace --shell /usr/sbin/nologin flowtrace
useradd --create-home --shell /bin/sh coleta
usermod -aG flowtrace coleta
install -d -o coleta -g flowtrace -m 2750 /dados
```

### Firewall
Só as portas 443 (site) e 22 (SSH, apenas com chave) ficam abertas. Em `/etc/ssh/sshd_config`, use `PasswordAuthentication no`.

### Banco
```sh
sudo -u postgres createuser flowtrace
sudo -u postgres createdb -O flowtrace flowtrace
```
A aplicação conecta pelo socket local com o usuário `flowtrace` (autenticação *peer*), sem senha. Em `config/.env`, defina `DB_NAME=flowtrace` e `DB_HOST=` (presente e vazio) para usar o socket; se a variável não existir, o padrão é `localhost`. Se preferir TCP, defina `DB_HOST=localhost` e `DB_PASSWORD`.

### Aplicação
```sh
sudo -u flowtrace -s
cd /srv/flowtrace
git clone <repositório> app
python3 -m venv venv && venv/bin/pip install -r app/requirements.txt
cp app/config/.env.example app/config/.env   # preencher: SECRET_KEY, ENCRYPTION_KEYS, DB_*, ALLOWED_HOSTS,
                                             # CSRF_TRUSTED_ORIGINS, FLOWTRACE_DATA_ROOT=/dados, TELEGRAM_*, HEALTHCHECKS_PING_URL
chmod 600 app/config/.env
cd app && ../venv/bin/python manage.py migrate && ../venv/bin/python manage.py collectstatic --noinput
../venv/bin/python manage.py createsuperuser
```

### Serviços
```sh
cp /srv/flowtrace/app/deploy/central/*.service /srv/flowtrace/app/deploy/central/*.timer /etc/systemd/system/
cp /srv/flowtrace/app/deploy/central/Caddyfile /etc/caddy/Caddyfile   # trocar o domínio
chmod +x /srv/flowtrace/app/deploy/central/backup.sh
systemctl daemon-reload
systemctl enable --now flowtrace.service flowtrace-coleta.timer flowtrace-integridade.timer flowtrace-backup.timer
systemctl reload caddy
```

| Rotina | Quando | O que faz |
|---|---|---|
| `flowtrace-coleta` | a cada 5 min | `check_collection`: situação da coleta, alerta no Telegram e SHA-256 dos arquivos novos |
| `flowtrace-integridade` | dia 1º, 04:00 | `verify_log_files --alert`: recalcula um dia sorteado e compara com o manifesto |
| `flowtrace-backup` | diário, 03:00 | dump do banco e cópia dos logs para o S3, e retenção local de 13 meses |

### Backup (S3 São Paulo)
1. Crie dois buckets em `sa-east-1`:
   - **logs**, com *Object Lock* em modo *compliance* (retenção padrão de 396 dias) e uma regra de ciclo de vida que expira em 396 dias;
   - **banco**, com versionamento e expiração em 30 dias.
2. Use um usuário IAM com permissão só de `PutObject`/`ListBucket` nesses buckets, sem `DeleteObject`.
3. Configure o remote como o usuário flowtrace: `sudo -u flowtrace rclone config` (tipo s3, provider AWS, region sa-east-1).
4. Copie `backup.env.example` para `/srv/flowtrace/backup.env` (`chmod 600`) e preencha.

### Monitoramento
- **Healthchecks**: crie um check para `check_collection` (período de 5 min, tolerância de 10 min) e outro para o backup (período de 1 dia), e coloque as URLs no `.env` e no `backup.env`. Se a rotina parar, o Healthchecks avisa.
- **Telegram**: crie um bot com o @BotFather e coloque `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` no `.env`. Os alertas avisam quando uma coleta para, quando ela volta e quando um arquivo é alterado depois de registrado.
- **Uptime Kuma** (ou similar), fora do servidor, para monitorar o site.

---

## 2. Novo cliente (organização e equipamento)

1. **No flowtrace (admin):** crie a organização.
2. **No cliente:** rode o kit do coletor numa VM Debian:
   ```sh
   ORG=<slug> EQUIP=<equipamento> CENTRAL=<host do central> ROUTER_IP=<ip do roteador> sh instalar-coletor.sh
   ```
3. **No central:** cole a linha `command="rrsync ..."` que o script imprime em `~coleta/.ssh/authorized_keys` e crie a pasta `/dados/<org>/<equip>` (o comando também é impresso).
4. **No roteador:** siga `deploy/coletor/roteiro-cisco.md`.
5. **No flowtrace (admin):** cadastre um servidor para a organização com **Acesso: Execução local**, pasta `/dados/<org>/<equip>` e o fuso do equipamento. Depois, em **Servidores → Testar**, confira se aparece "Último registro há X min".

Para registrar no manifesto os arquivos que já existiam:
`manage.py check_collection --server <id> --days 400 --no-alert`. A rotina processa 600 arquivos por servidor a cada execução (`MANIFEST_BATCH_SIZE`), então vá rodando até zerar os pendentes.

---

## 3. Migrar os dados do SQLite para o PostgreSQL

Os campos cifrados (credenciais, snapshots) são exportados ainda cifrados. Use as **mesmas** `ENCRYPTION_KEYS` no destino.

```sh
# Com o .env SEM DB_NAME (lendo o SQLite):
python manage.py dumpdata --natural-foreign --natural-primary \
  -e contenttypes -e auth.permission -e admin.logentry -e sessions --indent 2 > dados.json

# Com DB_NAME definido (PostgreSQL vazio):
python manage.py migrate
python manage.py loaddata dados.json
```

Confira entrando no sistema e testando um servidor. Depois apague o `dados.json`, que contém dados pessoais.
