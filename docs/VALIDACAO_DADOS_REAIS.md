# Validação de dados reais — Radar Pokémon Brasil

Este guia explica como validar conectores, distinguir dados **live** de **mock** e o que fazer quando uma fonte está bloqueada.

---

## Fluxo recomendado

### 1. Diagnóstico geral (primeiro passo)

```bash
python3 -m src.main doctor
```

O `doctor` testa:

| Fonte | O que verifica |
|-------|----------------|
| Mercado Livre | API pública de busca (HTTP + JSON) |
| Reddit | Endpoint público ou OAuth configurado |
| SQLite | Leitura/escrita do banco `data/radar.db` |
| CSV | Permissão de escrita em `data/` |
| `.env` | Variáveis opcionais (User-Agent, OAuth) |
| `config/cards.yml` | YAML válido |
| `config/keywords.yml` | YAML válido |
| `config/sources.yml` | YAML válido |

O resultado aparece em uma tabela com **status**, **data_mode**, **HTTP**, **mensagem** e **próxima ação**. Cada execução é salva na tabela `connector_health`.

### 2. Busca apenas com dados reais

```bash
python3 -m src.main reset-db --force
python3 -m src.main search --cards config/cards.yml --limit 20 --live-only
python3 -m src.main report
```

Com `--live-only`:

- Nunca usa mock.
- Se uma fonte falhar (403, timeout, sem credencial), registra erro e segue.
- O relatório mostra quantos resultados são `live`, `mock` e `manual_import`.

### 3. Demonstração com mock (offline)

```bash
python3 -m src.main reset-db --force
python3 -m src.main search --cards config/cards.yml --limit 20 --mock-only
python3 -m src.main report
```

Use apenas para testar o relatório e a interface — **não para decisão de mercado**.

### 4. Status histórico dos conectores

```bash
python3 -m src.main source-status
```

Mostra o último diagnóstico conhecido de cada fonte (baseado em `connector_health`).

### 5. Testes isolados por conector

```bash
python3 -m src.main test-mercadolivre --query "carta pokemon charizard"
python3 -m src.main test-reddit --query "pokemon tcg brasil charizard"
```

Esses comandos **não gravam em `radar_results`** — apenas salvam o diagnóstico em `connector_health`.

---

## Como diferenciar live de mock

Cada resultado tem o campo **`data_mode`**:

| Valor | Significado |
|-------|-------------|
| `live` | Coletado de API pública real |
| `mock` | Dado simulado — não use para decisão de mercado |
| `manual_import` | Importado manualmente (ex.: exportação Discord) |

No relatório, a seção **VALIDAÇÃO DOS DADOS** aparece no topo:

```
VALIDAÇÃO DOS DADOS
  • live: X resultados
  • mock: X resultados
  • manual_import: X resultados
  • fontes com erro: X
```

Se houver qualquer dado mock, o relatório exibe:

> **ATENÇÃO: este relatório contém dados simulados. Não use para decisão real de mercado.**

**Regra prática:** confie no relatório para decisões apenas se **live > 0** e **mock = 0**.

---

## Modos do comando `search`

| Flag | Comportamento |
|------|---------------|
| `--live-only` | Apenas APIs reais; sem fallback mock |
| `--allow-mock` | Padrão — tenta live primeiro, usa mock se falhar |
| `--mock-only` | Apenas dados simulados (demonstração) |

Use **apenas uma** flag por execução.

---

## O que significa HTTP 403

**HTTP 403 Forbidden** significa que o servidor **recusou** a requisição. Não é um erro de sintaxe nem de rede — é um bloqueio de acesso.

Causas comuns neste projeto:

1. **IP de datacenter** — muitas APIs bloqueiam servidores cloud/VPS.
2. **User-Agent genérico ou ausente** — Reddit exige identificação clara.
3. **Falta de credenciais oficiais** — alguns endpoints exigem OAuth ou token de app.

**Importante:** uma resposta 403 **não é dado real**. O Radar não salva resultados quando a API retorna `forbidden`.

### O que fazer se receber 403

**Mercado Livre:**

1. Rode `python3 -m src.main test-mercadolivre` para ver o corpo da resposta.
2. Teste em **rede residencial** (casa, 4G) — costuma funcionar melhor que datacenter.
3. Se tiver app registrado no Mercado Livre, configure `ML_ACCESS_TOKEN` no `.env`.
4. Não use proxy, scraping de HTML nem tentativas de burlar o bloqueio.

**Reddit:**

1. Configure um User-Agent descritivo no `.env` (veja abaixo).
2. Teste em rede residencial.
3. Configure OAuth se o endpoint público continuar bloqueado.

---

## Configurar Reddit OAuth no `.env`

1. Crie um app em [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) (tipo *script* ou *installed*).
2. Copie o exemplo:

```bash
cp .env.example .env
```

3. Edite `.env`:

```env
REDDIT_USER_AGENT=RadarPokemonBrasil/1.0 (seu@email.com)
REDDIT_CLIENT_ID=seu_client_id
REDDIT_CLIENT_SECRET=seu_client_secret
```

4. Rode `python3 -m src.main test-reddit` — o diagnóstico mostrará `Modo: oauth` ou `public`.

Sem credenciais, o conector usa o endpoint **público** com User-Agent. O teste isolado indica claramente qual modo está ativo.

---

## Tabela `connector_health`

Cada execução de `doctor`, `test-mercadolivre` ou `test-reddit` grava:

| Coluna | Descrição |
|--------|-----------|
| `source` | Nome da fonte (`mercado_livre`, `reddit`, `sqlite`, …) |
| `status` | `OK`, `WARNING`, `ERROR` |
| `data_mode` | `live`, `mock`, `unavailable` |
| `http_status` | Código HTTP quando aplicável |
| `message` | Resumo curto |
| `tested_at` | Data/hora UTC do teste |
| `raw_response_snippet` | Trecho da resposta (até 500 caracteres) |

Consulte o histórico com `source-status`.

---

## Por que não usamos scraping de Facebook, Instagram, WhatsApp ou grupos privados

O Radar Pokémon Brasil segue estas regras de conformidade:

| Plataforma | Motivo |
|------------|--------|
| **Facebook / Instagram** | Termos de uso proíbem scraping automatizado; APIs oficiais exigem aprovação e escopo limitado |
| **WhatsApp** | Mensagens são privadas; não há API pública de grupos |
| **Grupos privados (Discord, Telegram, etc.)** | Conteúdo fechado — acesso sem consentimento viola privacidade e ToS |
| **Login automatizado** | Não fazemos login em contas de terceiros nem burlamos captcha |

O MVP coleta apenas **dados públicos via APIs oficiais** (Reddit JSON, Mercado Livre Search API). Fontes futuras serão avaliadas com o mesmo critério — ver `docs/future_connectors_meta.md`.

---

## Resumo rápido

```bash
# Diagnóstico
python3 -m src.main doctor
python3 -m src.main source-status

# Validação real
python3 -m src.main search --live-only --limit 20
python3 -m src.main report

# Demonstração
python3 -m src.main search --mock-only --limit 5
```

Se `doctor` mostrar `ERROR` com HTTP 403 em ML ou Reddit, o ambiente atual está bloqueado — isso é esperado em datacenter e **não quebra o MVP**, mas também **não deve ser tratado como dado de mercado**.
