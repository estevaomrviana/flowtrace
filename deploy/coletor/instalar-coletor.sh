#!/bin/sh
# Kit do coletor de borda FlowTrace.
#
# Roda numa VM Debian 12 mínima dentro da rede do cliente (1 vCPU, 1 GB RAM, ~50 GB).
# Instala o nfcapd recebendo o NetFlow do roteador e envia os arquivos a cada
# 5 minutos para o servidor central, por rsync sobre SSH com chave exclusiva.
# O cliente não precisa abrir nenhuma porta: a conexão sai do coletor.
#
# Uso (como root):
#   ORG=provedor-x EQUIP=cisco-cgnat CENTRAL=coleta.flowtrace.com.br \
#   ROUTER_IP=10.0.0.1 sh instalar-coletor.sh
#
# Variáveis:
#   ORG        identificador da organização no flowtrace (slug)           obrigatório
#   EQUIP      nome do equipamento (letras, números e hífen)              obrigatório
#   CENTRAL    hostname do servidor central                               obrigatório
#   ROUTER_IP  IP de origem do NetFlow (roteador); só ele é aceito         obrigatório
#   PORT       porta UDP do NetFlow                         (padrão 2056)
#   CENTRAL_USER  usuário que recebe os arquivos no central (padrão coleta)
#   KEEP_DAYS  dias guardados localmente                    (padrão 30)
#   ROTATE     rotação do nfcapd em segundos                (padrão 300)
#   HC_URL     URL de ping do Healthchecks deste coletor    (opcional)
#
# O script pode ser rodado de novo para ajustar a configuração; a chave SSH é mantida.
set -eu

: "${ORG:?informe ORG}" "${EQUIP:?informe EQUIP}" "${CENTRAL:?informe CENTRAL}" "${ROUTER_IP:?informe ROUTER_IP}"
PORT="${PORT:-2056}"
CENTRAL_USER="${CENTRAL_USER:-coleta}"
KEEP_DAYS="${KEEP_DAYS:-30}"
ROTATE="${ROTATE:-300}"
HC_URL="${HC_URL:-}"

case "$ORG$EQUIP" in
  *[!a-z0-9-]*) echo "ORG e EQUIP: use só letras minúsculas, números e hífen." >&2; exit 1 ;;
esac

if [ "$(id -u)" != 0 ]; then
  echo "Rode como root." >&2; exit 1
fi

DATA="/var/cache/nfdump/$EQUIP"
CONF=/etc/flowtrace
KEY="$CONF/id_ed25519"

echo "==> Pacotes"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nfdump rsync openssh-client nftables curl >/dev/null

# O pacote do Debian traz um serviço próprio do nfcapd; usamos o nosso.
systemctl disable --now nfdump.service >/dev/null 2>&1 || true

id flowtrace >/dev/null 2>&1 || useradd --system --home-dir /var/cache/nfdump --shell /usr/sbin/nologin flowtrace
install -d -o flowtrace -g flowtrace -m 0750 "$DATA"
install -d -o root -g flowtrace -m 0750 "$CONF"

cat > "$CONF/coletor.env" <<EOF
ORG=$ORG
EQUIP=$EQUIP
CENTRAL=$CENTRAL
CENTRAL_USER=$CENTRAL_USER
DATA=$DATA
KEEP_DAYS=$KEEP_DAYS
HC_URL=$HC_URL
EOF
chmod 0640 "$CONF/coletor.env"; chgrp flowtrace "$CONF/coletor.env"

echo "==> nfcapd (UDP $PORT, rotação de $ROTATE s, pastas AAAA/MM/DD, compressão LZO)"
cat > /etc/systemd/system/flowtrace-nfcapd.service <<EOF
[Unit]
Description=FlowTrace - coletor NetFlow ($EQUIP)
After=network-online.target
Wants=network-online.target

[Service]
User=flowtrace
Group=flowtrace
ExecStart=/usr/bin/nfcapd -w $DATA -S 1 -t $ROTATE -p $PORT -z
Restart=always
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$DATA
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

echo "==> Chave SSH exclusiva deste coletor"
if [ ! -f "$KEY" ]; then
  ssh-keygen -q -t ed25519 -N '' -C "coletor-$ORG-$EQUIP" -f "$KEY"
fi
chown root:flowtrace "$KEY" "$KEY.pub"; chmod 0640 "$KEY"

echo "==> Envio a cada 5 minutos"
cat > /usr/local/bin/flowtrace-enviar <<'EOF'
#!/bin/sh
# Envia os arquivos fechados do nfcapd para o central e apaga localmente os mais antigos que KEEP_DAYS.
set -eu
. /etc/flowtrace/coletor.env
KH=/etc/flowtrace/known_hosts

status=0
rsync -a --partial-dir=.rsync-partial \
  --exclude 'nfcapd.current.*' --exclude '.nfstat' --exclude '.rsync-partial' \
  -e "ssh -i /etc/flowtrace/id_ed25519 -o IdentitiesOnly=yes -o UserKnownHostsFile=$KH -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20" \
  "$DATA/" "$CENTRAL_USER@$CENTRAL:./" || status=$?

# Retenção local (buffer): só apaga o que já passou do prazo.
find "$DATA" -type f -name 'nfcapd.[0-9]*' -mtime +"$KEEP_DAYS" -delete
find "$DATA" -mindepth 1 -type d -empty -delete

if [ -n "$HC_URL" ]; then
  if [ "$status" = 0 ]; then curl -fsS -m 10 --retry 3 "$HC_URL" >/dev/null || true
  else curl -fsS -m 10 --retry 3 "$HC_URL/fail" >/dev/null || true; fi
fi
exit "$status"
EOF
chmod 0755 /usr/local/bin/flowtrace-enviar
touch "$CONF/known_hosts"; chown root:flowtrace "$CONF/known_hosts"; chmod 0660 "$CONF/known_hosts"

cat > /etc/systemd/system/flowtrace-enviar.service <<EOF
[Unit]
Description=FlowTrace - envio dos arquivos para o servidor central
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=flowtrace
Group=flowtrace
ExecStart=/usr/local/bin/flowtrace-enviar
EOF

cat > /etc/systemd/system/flowtrace-enviar.timer <<EOF
[Unit]
Description=FlowTrace - envio a cada 5 minutos

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
RandomizedDelaySec=30

[Install]
WantedBy=timers.target
EOF

echo "==> Firewall: UDP $PORT aceito só de $ROUTER_IP"
cat > /etc/nftables-flowtrace.conf <<EOF
table inet flowtrace {
  chain input {
    type filter hook input priority -10; policy accept;
    udp dport $PORT ip saddr != $ROUTER_IP drop
  }
}
EOF
grep -q 'nftables.d-flowtrace.conf' /etc/nftables.conf 2>/dev/null || \
  echo 'include "/etc/nftables-flowtrace.conf"' >> /etc/nftables.conf
systemctl enable --now nftables >/dev/null
nft -f /etc/nftables.conf

systemctl daemon-reload
systemctl enable --now flowtrace-nfcapd.service flowtrace-enviar.timer

cat <<EOF

Coletor instalado.

1) No servidor central, autorize esta chave (uma linha em ~$CENTRAL_USER/.ssh/authorized_keys):

command="rrsync /dados/$ORG/$EQUIP/",restrict $(cut -d' ' -f1,2 "$KEY.pub") coletor-$ORG-$EQUIP

   e crie a pasta:  install -d -o $CENTRAL_USER -g flowtrace -m 2750 /dados/$ORG/$EQUIP

2) No roteador, aponte o NetFlow para este coletor, porta UDP $PORT
   (roteiro Cisco: deploy/coletor/roteiro-cisco.md).

3) Confira:
   systemctl status flowtrace-nfcapd     # recebendo?
   ls -R $DATA | tail                    # arquivos nfcapd.AAAAMMDDhhmm a cada $ROTATE s
   sudo -u flowtrace /usr/local/bin/flowtrace-enviar   # primeiro envio (aceita a chave do central)

4) No flowtrace (admin da plataforma), cadastre o servidor da organização em
   "Execução local" com a pasta /dados/$ORG/$EQUIP.
EOF
