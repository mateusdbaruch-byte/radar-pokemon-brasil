# Opportunity Radar — automação permitida

O **Radar Pokémon Brasil** é um **Opportunity Radar**: automatiza a busca de oportunidades e potenciais interessados em cartas Pokémon TCG no Brasil, dentro dos limites legais e técnicos.

---

## Objetivo

Detectar automaticamente:

- Compradores potenciais (*"procuro Charizard"*, *"compro Umbreon"*)
- Vendedores e desapegos públicos
- Leads opt-in da lista de desejos
- Anúncios em marketplaces autorizados

**Não** é um sistema manual de estoque ou precificação.

---

## Fontes automatizáveis (MVP)

| Fonte | Status | Como funciona |
|-------|--------|---------------|
| **web_search** | LIVE com API key | Bing / Google Custom Search / SerpAPI via `.env` |
| **wishlist** | LIVE | Leads opt-in cadastrados ou importados |
| **mercado_livre** | LIVE (pode 403) | API oficial de busca |
| **reddit** | Gated | OAuth + Responsible Builder Policy |

### Busca web — queries de intenção

O conector `web_search` usa templates como:

- `procuro {carta} "Pokémon TCG"`
- `compro {carta} "Pokémon TCG"`
- `"alguém vende" {carta} "Pokémon TCG"`
- `"desapego" {carta} "Pokémon TCG"`
- `"abaixo da Liga" {carta} "Pokémon TCG"`
- `pago {carta} Pokémon`
- `"quero comprar" {carta} "Pokémon TCG"`

**Não fazemos scraping de Google.** Apenas APIs oficiais configuráveis:

```env
WEB_SEARCH_PROVIDER=bing
BING_SEARCH_API_KEY=sua_chave
```

Alternativas: `google` (com `GOOGLE_SEARCH_API_KEY` + `GOOGLE_SEARCH_ENGINE_ID`) ou `serpapi`.

---

## Fontes PENDING_ACCESS (futuro)

Sem acesso autorizado no MVP — marcadas como `PENDING_ACCESS`:

| Marketplace | Motivo |
|-------------|--------|
| OLX | Sem API pública autorizada |
| Shopee | Requer parceria/API |
| BigDex | Aguardando acesso permitido |
| LigaPokemon | Sem scraping — API/parceria futura |
| MYP Cards | Sem scraping — API/parceria futura |

---

## Bots e Meta autorizados (placeholders)

Conectores preparados para crescimento com **opt-in explícito**:

| Conector | Requisito |
|----------|-----------|
| `discord_bot` | Bot adicionado ao canal com permissão |
| `telegram_bot` | Bot em grupo/canal com opt-in |
| `instagram_pro` | Conta profissional própria via Meta API |
| `facebook_page` | Página própria via Graph API |

**Não implementado no MVP** — estrutura pronta para quando houver autorização.

---

## O que NÃO rastreamos

| Plataforma | Motivo |
|------------|--------|
| Facebook/Instagram de terceiros | Scraping proibido; apenas conta própria via API |
| WhatsApp | Privado; sem API de grupos |
| DMs e grupos privados | Sem consentimento |
| Login automatizado | Não burlamos captcha ou bloqueios |
| Proxy / scraping irregular | Não usamos |

---

## Lista de desejos (opt-in)

Leads que **autorizaram** ser contactados:

```bash
python -m src.main add-wishlist-lead --name "João" --card Charizard --contact joao@email.com
python -m src.main import-wishlist data/imports/wishlist_example.csv
```

Tabela `wishlist_leads`: nome, contato, carta, coleção, urgência, preço máximo, etc.

---

## Fluxo principal

```bash
python -m src.main doctor
python -m src.main reset-db --force
python -m src.main import-wishlist data/imports/wishlist_example.csv   # opt-in
python -m src.main scan-opportunities --cards config/watchlist.yml --sources web_search,wishlist --limit 20
python -m src.main opportunity-inbox
python -m src.main opportunity-report
```

Configure `WEB_SEARCH_PROVIDER` no `.env` para ativar busca web automatizada.

---

## Tabela `opportunities`

Cada oportunidade tem:

- `opportunity_type` — buyer_intent, seller_intent, wishlist_lead, web_signal…
- `intent_score`, `urgency_score`, `opportunity_score`, `confidence_score`
- `evidence_text`, `url`, `recommended_action`
- `data_mode` — live (nunca mock no fluxo principal)

---

## Como crescer

1. **APIs oficiais** — Bing/Google/SerpAPI para busca web
2. **Wishlist opt-in** — parceiros, formulário, importação CSV
3. **Marketplaces** — parcerias OLX, Shopee, Liga, MYP
4. **Bots autorizados** — Discord/Telegram em canais com permissão
5. **Meta API** — Instagram/Facebook da marca própria
6. **Reddit** — após aprovação Responsible Builder Policy

O foco permanece: **automatizar oportunidades dentro dos limites permitidos**.
