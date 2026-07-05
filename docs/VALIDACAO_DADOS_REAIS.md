# Validação de dados reais — Radar Pokémon Brasil

Este guia explica como validar o MVP com dados **reais** (`live` ou `manual_import`), distinguir de **mock** e lidar com bloqueios de API.

---

## Quando o MVP está validado?

O MVP só é considerado **validado para decisão de mercado** quando houver dados com:

| `data_mode` | Validação |
|-------------|-----------|
| `live` | Coletado de API real (Reddit OAuth, etc.) |
| `manual_import` | Importado de CSV confiável (LigaPokemon, MYP Cards) |
| `mock` | **Não valida** — serve apenas para testar interface e relatório |

**Regra:** `mock = 0` e (`live > 0` ou `manual_import > 0`).

O comando `market-snapshot` mostra apenas `live` + `manual_import` — nunca mock.

---

## Fluxo de primeira validação

### 1. Configurar `.env`

```bash
python3 -m src.main setup-env
```

- Cria `.env` a partir de `.env.example` se não existir
- Lista variáveis a preencher manualmente
- **Não pede senha no terminal** — edite o arquivo no editor

### 2. Testar Reddit OAuth

```bash
python3 -m src.main test-reddit-auth
```

- Mostra quais campos estão preenchidos (valores ocultos)
- Tenta autenticar via OAuth (`client_credentials` ou `password` grant)
- Faz busca de teste por `"pokemon tcg brasil"`
- **Não salva em `radar_results`**

### 3. Coletar dados live do Reddit

```bash
python3 -m src.main reset-db --force
python3 -m src.main search-reddit --query "pokemon tcg brasil" --limit 10
python3 -m src.main report
```

### 4. Importar preços manuais

Alternativa quando APIs estão bloqueadas:

```bash
python3 -m src.main validate-import data/imports/manual_prices_example.csv
python3 -m src.main import-prices data/imports/manual_prices_example.csv
python3 -m src.main market-snapshot
```

Colunas do CSV: `source`, `card_name`, `price`, `currency`, `condition`, `language`, `url`, `seller`, `collected_at`

Fontes aceitas: `liga_pokemon`, `myp_cards`, `manual`, `mercado_livre`

### 5. Diagnóstico geral

```bash
python3 -m src.main doctor
python3 -m src.main source-status
```

---

## Reddit — OAuth e User-Agent

O Reddit exige identificação clara. Para OAuth:

1. Crie app em [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps)
2. Preencha no `.env`:

```env
REDDIT_CLIENT_ID=seu_client_id
REDDIT_CLIENT_SECRET=seu_client_secret
REDDIT_USER_AGENT=python:radar-pokemon-brasil:v0.1.0 (by /u/SEU_USUARIO)
```

3. **Opcional** — grant password (app tipo *script*):

```env
REDDIT_USERNAME=seu_usuario
REDDIT_PASSWORD=sua_senha
```

Se `REDDIT_USERNAME` e `REDDIT_PASSWORD` estiverem vazios, o conector usa `client_credentials` (read-only).

**Status salvos em `connector_health`:**

| Status | Significado |
|--------|-------------|
| `live` | OAuth OK e/ou busca funcionando |
| `auth_failed` | Credenciais rejeitadas |
| `missing_credentials` | `.env` incompleto |
| `blocked` | HTTP 403 — IP/rede bloqueado |

---

## Mercado Livre — modo diagnóstico

A API pública do Mercado Livre pode retornar **HTTP 403** em IPs de datacenter. Isso **não trava o MVP**:

- `test-mercadolivre` e `doctor` continuam diagnosticando
- Respostas `forbidden` **não são salvas** como dados reais
- Use Reddit OAuth ou `import-prices` como fontes alternativas
- Teste ML em rede residencial ou com `MERCADOLIVRE_ACCESS_TOKEN` se tiver app oficial

```bash
python3 -m src.main test-mercadolivre --query "carta pokemon charizard"
```

---

## Busca por fonte específica

```bash
# Apenas Reddit (live)
python3 -m src.main search --sources reddit --live-only --limit 20

# Reddit + Mercado Livre (ML pode falhar sem derrubar Reddit)
python3 -m src.main search --sources mercado_livre,reddit --live-only
```

Se uma fonte falhar, as outras continuam.

---

## Mock — apenas demonstração

```bash
python3 -m src.main search --mock-only --limit 5
```

Use **somente** para:
- Testar relatório e interface offline
- Demonstrações sem API

O relatório exibe aviso vermelho quando há mock:

> ATENÇÃO: este relatório contém dados simulados. Não use para decisão real de mercado.

---

## O que fica fora do MVP

Sem opt-in ou autorização explícita, **não coletamos**:

| Plataforma | Motivo |
|------------|--------|
| Facebook / Instagram | ToS proíbem scraping; APIs restritas |
| WhatsApp | Mensagens privadas |
| Discord / Telegram privado | Grupos fechados |
| Login automatizado irregular | Não burlamos captcha ou bloqueios |

Apenas APIs públicas oficiais e importação manual autorizada pelo usuário.

---

## Resumo de comandos

```bash
python3 -m src.main setup-env
python3 -m src.main test-reddit-auth
python3 -m src.main search-reddit --query "pokemon tcg brasil" --limit 10
python3 -m src.main validate-import data/imports/manual_prices_example.csv
python3 -m src.main import-prices data/imports/manual_prices_example.csv
python3 -m src.main market-snapshot
python3 -m src.main doctor
```
