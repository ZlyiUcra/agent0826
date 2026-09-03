# Підготовка практики модуля 8 з нуля

Шлях від чистого клона до агента специфікації, який відповідає з Kubernetes. Кроки йдуть у порядку
виконання; що вже стоїть — пропускайте. Усі команди виконуються з теки `module8/`.

## 1. Оточення Python і ключ

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install fastembed==0.8.0
cp .env.example .env                      # і впишіть ANTHROPIC_API_KEY
```

`fastembed` ставиться окремим рядком свідомо: у `requirements.txt` його немає, як і в модулях 6 і 7 —
без нього все працює, лише пошук іде по словах замість пошуку за змістом. Модель векторів bge-small
(128 МБ) він стягне сам на першому використанні.

## 2. Інструменти деплою

Docker потрібен установлений і запущений. Решта — три статичні бінарники, без root і без акаунтів:

```bash
cd ~/.local/bin        # тека має бути в PATH
curl -sL -o kubectl "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
curl -sL -o k3d "https://github.com/k3d-io/k3d/releases/latest/download/k3d-linux-amd64"
curl -sL -o cloudflared "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
chmod +x kubectl k3d cloudflared
```

На машині практики це kubectl v1.37.0, k3d v5.9.0, cloudflared 2026.8.3. `cloudflared` потрібен лише
для показу сервісу з чужого комп'ютера — якщо такого показу не буде, його можна не ставити.

## 3. Вектори для пошуку за змістом

```bash
.venv/bin/python -m practice.base.setup --status     # що вирішено і що в базі, безкоштовно
.venv/bin/python -m practice.base.setup --vectors    # підняти Qdrant і залити колекцію
```

Другий крок піднімає контейнер Qdrant у Docker і заливає колекцію `spec8-suite-bge-small`. З порожньої
бази це рахує ембединги всього корпусу — на повільному диску десятки хвилин; повторні запуски рахують
лише нове й змінене. Крок можна пропустити цілком: без колекції і локальний сервіс, і под шукатимуть по
словах і чесно про це скажуть у лозі.

## 4. Локальний сервіс

```bash
.venv/bin/uvicorn practice.api:app --port 8001
curl -s localhost:8001/health                        # {"ok":true}
curl -s localhost:8001/ask -X POST -H 'content-type: application/json' \
     -d '{"query": "Чому typeof null дає object?"}'
```

Перший запит після старту повільніший: сервер знань піднімається підпроцесом, індексує корпус і чекає
на прогрів векторів (`PRACTICE_VECTORS_WAIT=1` вшито в образ; локально його виставляти не обов'язково).
Відповідь містить `session_id`; додайте його в наступний запит — і агент продовжить ту саму розмову.
Локально історії сесій лежать у `practice/out/sessions/`, у поді — на окремому томі.

## 5. Ключ із лімітом для деплою

Сервісу, який дивиться назовні, потрібен не ключ з пункту 1, а окремий — із простору, де стоїть межа
витрат. Робиться в консолі Anthropic (console.anthropic.com), точні назви пунктів можуть трохи
відрізнятися:

1. Settings → Workspaces → Create workspace, назвіть, наприклад, `agentpro-deploy`.
2. У налаштуваннях цього простору знайдіть ліміт витрат (Spend limit) і поставте $2 на місяць.
3. Settings → API keys → Create key, у полі простору виберіть `agentpro-deploy`, ключ скопіюйте.
4. У `module8/.env` допишіть рядок `ANTHROPIC_API_KEY_DEPLOY=sk-ant-...`.

`practice/deploy/up.sh` бере цей ключ першим і кладе його в Secret кластера. Коли простір досягне $2 за
місяць, запити сервісу почнуть повертати помилку — ваш основний ключ і його рахунок цього не відчують.

## 6. Под у Kubernetes

```bash
./practice/deploy/up.sh
kubectl get pods                                     # spec-agent-...  2/2  Running
kubectl port-forward svc/spec-agent 8081:80          # в іншому терміналі
curl -s localhost:8081/ask -X POST -H 'content-type: application/json' \
     -d '{"query": "Що робить Array.prototype.at із відємним аргументом?"}'
```

Скрипт збирає образ, за потреби створює кластер (образом `rancher/k3s:v1.30.6-k3s1` — чому саме ним,
розповідає розділ про пастку в `README.md`), завозить образ, випускає Secret, ставить под і перевозить
вектори знімком із локального Qdrant. Якщо локального Qdrant немає, останній крок пропускається, і под
шукає по словах.

## 7. Перевірки, які нічого не коштують

```bash
docker run --rm spec-agent-m8:local                  # без ключа: падає з кодом 1, не працює
kubectl delete pod -l app=spec-agent                 # рестарт: вектори лишаються, out/ агента чиста
kubectl rollout status deployment/spec-agent
kubectl logs deployment/spec-agent -c agent | grep "пошук за змістом"
```

## 8. Прибрати за собою

```bash
k3d cluster delete agentpro
docker rmi spec-agent-m8:local
```
