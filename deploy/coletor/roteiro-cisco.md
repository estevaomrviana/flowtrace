# Roteiro: Cisco (NAT logging via NetFlow v9)

> Rascunho a partir da configuração usada hoje pelo Diagol. **Falta validar com ele** os itens marcados com ⚠️.

## 1. Pré-requisitos

- O coletor de borda já instalado (`deploy/coletor/instalar-coletor.sh`) e com IP fixo na rede do cliente.
- A porta UDP do coletor (padrão `2056`) acessível a partir do roteador. O firewall do coletor só aceita o IP de origem informado em `ROUTER_IP`.

## 2. Configuração no roteador

```
configure terminal
 ip nat log translations flow-export v9 udp destination <IP_DO_COLETOR> 2056 bind-only
end
write memory
```

| Parte | Função |
|---|---|
| `ip nat log translations` | registra as traduções de NAT (IP privado → IP e porta públicos) |
| `flow-export v9` | exporta em NetFlow v9 |
| `udp destination <IP> 2056` | destino: o coletor de borda |
| `bind-only` | envia só a criação e a remoção dos *bindings*, não cada tradução (reduz muito o volume) |

⚠️ Confirmar:
- se o `bind-only` atende o que a Anatel e o Judiciário pedem (porta de origem, início e fim, fuso);
- se é preciso fixar a interface de origem do export (`source`), para o IP de origem bater com o `ROUTER_IP` do firewall;
- quais versões do IOS / IOS-XE suportam o comando igual.

## 3. Conferência

No roteador:
```
show running-config | include nat log
show ip nat statistics
```

No coletor:
```
systemctl status flowtrace-nfcapd
ls -lR /var/cache/nfdump/<EQUIP> | tail      # um arquivo nfcapd.AAAAMMDDhhmm a cada 5 min
nfdump -R /var/cache/nfdump/<EQUIP>/$(date +%Y/%m/%d) -c 5
```

No flowtrace: em **Servidores**, clique em **Testar**. A coluna **Coleta** deve mostrar "Último registro há X min".

## 4. Próximos fabricantes

MikroTik e Huawei (comuns em provedores pequenos). A ideia é ter um roteiro como este para cada um, com o mesmo coletor de borda.
