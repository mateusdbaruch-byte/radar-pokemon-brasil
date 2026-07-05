# Validação de dados reais — Radar Pokémon Brasil

Este guia explica como validar o MVP com dados **reais** (`live` ou `manual_import`), distinguir de **mock** e lidar com fontes bloqueadas ou gated.

---

## Quando o MVP está validado?

O MVP só é considerado **validado para decisão de mercado** quando houver dados com:

| `data_mode` | Validação |
|-------------|-----------|
| `live` | Coletado de API real (Mercado Livre, Reddit aprovado…) |
| `manual_import` | Importado de CSV confiável (LigaPokemon, MYP Cards) |
| `mock` | **Não valida** — serve apenas para testar interface e relatório |

**Regra:** `mock = 0` e (`live > 0` ou `manual_import > 0`).

**Reddit não bloqueia a validação do MVP.** Use importação manual e Mercado Livre enquanto o Reddit estiver em aprovação.

O comando `market-snapshot` mostra apenas `live` + `manual_import` — nunca mock.

---

## Fluxo recomendado do MVP

### 1. Preços reais — importação manual (prioridade)

```bash
python3 -m src.main validate-import data/imports/manual_prices_example.csv
python3 -m src.main import-prices data/imports/manual_prices_example.csv
python3 -m src.main market-snapshot
```

### 2. Mercado Livre (quando disponível)

```bash
python3 -m src.main test-mercadolivre
python3 -m src.main search --sources mercado_livre --live-only --limit 20
```

HTTP 403 no ML é comum em datacenter — modo diagnóstico, não trava o MVP.

### 3. Reddit — fonte opcional após aprovação

```bash
python3 -m src.main setup-env
python3 -m src.main reddit-policy-status
python3 -m src.main test-reddit-auth
```

---

## Reddit — fonte gated / pending approval

O Reddit exige leitura da **Responsible Builder Policy** e pode exigir **aprovação explícita** para uso da API.

**Não fazemos:**
- Scraping de HTML
- Bypass de captcha, login ou bloqueios
- Contorno de políticas ou rate limits

**Quando a API retorna 403 ou mensagem de política/aprovação:**

| Comportamento | Detalhe |
|---------------|---------|
| Status | `PENDING_APPROVAL` em `connector_health` |
| Busca | Fonte pulada — execução continua com outras fontes |
| Mock | Nunca usado automaticamente |
| Mensagem | *Reddit API requires approval/configuration. This source is disabled until credentials and approval are available.* |

```bash
python3 -m src.main reddit-policy-status
```

**Para uso comercial ou escala:** solicite aprovação oficial no [Reddit Developer Portal](https://www.reddit.com/prefs/apps) e cumpra a Responsible Builder Policy.

### Status possíveis em `connector_health`

| Status | Significado |
|--------|-------------|
| `OK` | Fonte operacional |
| `WARNING` | Aviso não crítico |
| `ERROR` | Falha técnica |
| `BLOCKED` | Bloqueio de IP/rede (ex.: Mercado Livre 403) |
| `PENDING_APPROVAL` | Reddit aguardando aprovação/configuração |
| `REQUIRES_AUTH` | Credenciais OAuth/User-Agent ausentes |

---

## Doctor — o que é erro crítico?

O `doctor` **só indica falha crítica do ambiente** quando:

- SQLite inacessível
- Escrita CSV falha
- Arquivos `config/*.yml` inválidos ou ausentes

Reddit em `PENDING_APPROVAL` ou Mercado Livre em `BLOCKED` são **avisos de fonte**, não falha do sistema.

```bash
python3 -m src.main doctor
```

---

## Configurar Reddit (quando aprovado)

```bash
python3 -m src.main setup-env
```

Edite `.env` manualmente:

```env
REDDIT_CLIENT_ID=seu_client_id
REDDIT_CLIENT_SECRET=seu_client_secret
REDDIT_USER_AGENT=python:radar-pokemon-brasil:v0.1.0 (by /u/SEU_USUARIO)
```

Teste:

```bash
python3 -m src.main test-reddit-auth
python3 -m src.main search-reddit --query "pokemon tcg brasil" --limit 10
```

---

## Busca por fonte

```bash
# Só Mercado Livre — Reddit pending não derruba a execução
python3 -m src.main search --sources mercado_livre --live-only

# Reddit só se aprovado
python3 -m src.main search --sources reddit --live-only
```

---

## Mock — apenas demonstração

```bash
python3 -m src.main search --mock-only --limit 5
```

Não use mock para validar mercado.

---

## Fora do MVP (sem opt-in)

| Plataforma | Motivo |
|------------|--------|
| Facebook / Instagram | Scraping proibido; APIs restritas |
| WhatsApp | Privado |
| Discord / grupos privados | Sem autorização |
| Bypass de políticas | Não implementado |

---

## Resumo de comandos

```bash
python3 -m src.main import-prices data/imports/manual_prices_example.csv
python3 -m src.main market-snapshot
python3 -m src.main reddit-policy-status
python3 -m src.main doctor
```
