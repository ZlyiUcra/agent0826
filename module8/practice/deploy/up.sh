#!/usr/bin/env bash
# Практика М8 наскрізь: образ агента → кластер → секрет → под (агент + Qdrant
# поруч) → вектори знімком. Потрібні Docker, kubectl і k3d; хмара не потрібна.
#
# Вектори не рахуються наново: якщо поруч є Qdrant з готовою колекцією
# (SRC_QDRANT, типово локальний http://localhost:6333), звідти знімається
# знімок і відновлюється в поді. Немає джерела — под живе, а сервер знань
# чесно з'їжджає на пошук по словах, доки колекцію не завезуть.
set -euo pipefail
cd "$(dirname "$0")/../.."                       # корінь module8/

# Ключ у под їде свій, не той, яким користуються з термінала: окремий рядок
# ANTHROPIC_API_KEY_DEPLOY у module8/.env — ключ з простору, де стоїть місячний
# ліміт витрат (як його зробити — README, розділ про бюджет). Немає окремого —
# береться звичайний ключ модуля. Явно виставлений ANTHROPIC_API_KEY сильніший
# за обидва.
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -f .env ]; then
    ANTHROPIC_API_KEY=$(grep -m1 '^ANTHROPIC_API_KEY_DEPLOY=' .env | cut -d= -f2-)
    [ -n "$ANTHROPIC_API_KEY" ] || ANTHROPIC_API_KEY=$(grep -m1 '^ANTHROPIC_API_KEY=' .env | cut -d= -f2-)
fi
: "${ANTHROPIC_API_KEY:?немає ключа: впишіть ANTHROPIC_API_KEY_DEPLOY у module8/.env}"
SRC_QDRANT="${SRC_QDRANT:-http://localhost:6333}"
SRC_COLLECTION="${SRC_COLLECTION:-spec8-suite-bge-small}"
DST_COLLECTION="spec8-suite-bge-small"

echo "1/6 образ агента"
docker build -q --provenance=false --sbom=false \
    -t spec-agent-m8:local -f practice/Dockerfile . >/dev/null

echo "2/6 кластер"
# Образ k3s тут старіший навмисно: kubelet свіжих версій відмовляється
# стартувати на cgroup v1, а саме його дає ядро WSL2 5.15.
k3d cluster list 2>/dev/null | grep -q '^agentpro' \
    || k3d cluster create agentpro --agents 0 --wait --timeout 300s \
           --image rancher/k3s:v1.30.6-k3s1 >/dev/null 2>&1

echo "3/6 образ у кластер"
k3d image import spec-agent-m8:local -c agentpro >/dev/null 2>&1

echo "4/6 секрет"
kubectl create secret generic spec-agent-secrets \
    --from-literal=ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null

echo "5/6 под"
kubectl apply -f practice/deploy/pod.yaml >/dev/null
kubectl rollout status deployment/spec-agent --timeout=300s

echo "6/6 вектори знімком"
kubectl port-forward deploy/spec-agent 16333:6333 >/dev/null 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null' EXIT
for i in $(seq 1 20); do
    curl -sf localhost:16333/collections >/dev/null 2>&1 && break
    sleep 1
done

have=$(curl -sf "localhost:16333/collections/$DST_COLLECTION" 2>/dev/null \
       | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['points_count'])" \
       2>/dev/null || echo 0)
if [ "$have" -gt 0 ]; then
    echo "  колекція вже в поді: $have точок — знімок не потрібен"
elif ! curl -sf "$SRC_QDRANT/collections/$SRC_COLLECTION" >/dev/null 2>&1; then
    echo "  джерела векторів немає ($SRC_QDRANT) — под працюватиме з пошуком по словах"
else
    name=$(curl -sf -X POST "$SRC_QDRANT/collections/$SRC_COLLECTION/snapshots" \
           | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['name'])")
    tmp=$(mktemp /tmp/spec8-snapshot-XXXX.snapshot)
    curl -sf -o "$tmp" "$SRC_QDRANT/collections/$SRC_COLLECTION/snapshots/$name"
    echo "  знімок $name: $(du -h "$tmp" | cut -f1)"
    curl -sf -X POST \
        "localhost:16333/collections/$DST_COLLECTION/snapshots/upload?priority=snapshot" \
        -F "snapshot=@$tmp" >/dev/null
    rm -f "$tmp"
    curl -sf -X DELETE "$SRC_QDRANT/collections/$SRC_COLLECTION/snapshots/$name" >/dev/null || true
    got=$(curl -sf "localhost:16333/collections/$DST_COLLECTION" \
          | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['points_count'])")
    echo "  відновлено в поді: $got точок"
fi

echo
echo "Готово. В іншому терміналі:  kubectl port-forward svc/spec-agent 8081:80"
echo "і тоді:  curl -s localhost:8081/ask -X POST -H 'content-type: application/json' \\"
echo "            -d '{\"query\":\"Чому typeof null дає object?\"}'"
