#!/bin/sh
# Backup diário do FlowTrace (rodado pelo flowtrace-backup.timer).
#
# 1. Dump do PostgreSQL -> S3 (bucket com versionamento; expira em 30 dias).
# 2. Arquivos fechados do nfcapd em /dados -> S3 São Paulo (bucket com Object Lock
#    em modo compliance e expiração de 13 meses configurados no próprio bucket).
#    "copy" nunca apaga nada no destino.
# 3. Retenção local: apaga arquivos com mais de RETENTION_DAYS (padrão 396 = 13 meses).
#
# Variáveis (em /srv/flowtrace/backup.env):
#   DB_NAME            banco do flowtrace
#   RCLONE_REMOTE      remote do rclone já configurado (ex.: s3sp)
#   BUCKET_DB          bucket dos dumps do banco
#   BUCKET_LOGS        bucket dos logs (Object Lock)
#   DATA_ROOT          pasta dos logs (padrão /dados)
#   RETENTION_DAYS     dias de retenção local (padrão 396)
#   HC_BACKUP_URL      ping do Healthchecks para o backup (opcional)
set -eu

DATA_ROOT="${DATA_ROOT:-/dados}"
RETENTION_DAYS="${RETENTION_DAYS:-396}"
STAMP="$(date +%Y-%m-%d)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() {
  [ -n "${HC_BACKUP_URL:-}" ] && curl -fsS -m 10 --retry 3 "$HC_BACKUP_URL/fail" >/dev/null || true
  echo "backup falhou: $1" >&2
  exit 1
}

pg_dump --format=custom --no-owner "$DB_NAME" > "$TMP/flowtrace-$STAMP.dump" || fail "pg_dump"
rclone copyto "$TMP/flowtrace-$STAMP.dump" "$RCLONE_REMOTE:$BUCKET_DB/flowtrace-$STAMP.dump" || fail "envio do dump"

# Só arquivos rotacionados (o nfcapd/rsync não mexe mais neles).
rclone copy "$DATA_ROOT" "$RCLONE_REMOTE:$BUCKET_LOGS" \
  --include '*/*/[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/nfcapd.[0-9]*' \
  --min-age 10m --immutable || fail "envio dos logs"

find "$DATA_ROOT" -type f -name 'nfcapd.[0-9]*' -mtime +"$RETENTION_DAYS" -delete
find "$DATA_ROOT" -mindepth 3 -type d -empty -delete

[ -n "${HC_BACKUP_URL:-}" ] && curl -fsS -m 10 --retry 3 "$HC_BACKUP_URL" >/dev/null || true
echo "backup concluído: $STAMP"
