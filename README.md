# Radar Pokémon Brasil 🇧🇷

MVP de inteligência de demanda para cartas **Pokémon TCG** no Brasil.  
Coleta sinais públicos de compra/venda em fontes acessíveis e classifica a intenção de cada menção.

---

## O que este projeto faz?

1. Monitora uma lista de cartas Pokémon (ex.: Charizard, Umbreon, Pikachu…)
2. Busca menções em fontes públicas (Reddit, Mercado Livre, etc.)
3. Classifica se há intenção de **compra**, **venda**, **referência de preço** ou **discussão**
4. Atribui um **score de 0 a 100** para priorizar os melhores sinais
5. Salva tudo em **SQLite** e **CSV**
6. Mostra um relatório colorido no terminal

> **Importante:** Este MVP **não** envia mensagens, **não** faz login automático em redes sociais e **não** acessa grupos privados. Apenas coleta informações públicas para análise manual.

---

## Requisitos

- **Python 3.11 ou superior** — [baixar em python.org](https://www.python.org/downloads/)
- Conexão com a internet
- (Opcional) Chave da API do YouTube para habilitar comentários

---

## Instalação passo a passo

### 1. Baixar o projeto

Se você recebeu o código em uma pasta, abra o terminal nessa pasta.  
Exemplo no Linux/Mac:

```bash
cd radar-pokemon-brasil
```

No Windows, abra o **Prompt de Comando** ou **PowerShell** e navegue até a pasta.

### 2. Criar ambiente virtual (recomendado)

```bash
python3 -m venv .venv
```

Ativar o ambiente:

- **Linux/Mac:**
  ```bash
  source .venv/bin/activate
  ```
- **Windows:**
  ```bash
  .venv\Scripts\activate
  ```

### 3. Instalar dependências

```bash
pip install -r requirements.txt
```

### 4. Configurar variáveis de ambiente (opcional)

```bash
cp .env.example .env
```

Edite o arquivo `.env` se quiser personalizar o User-Agent do Reddit ou adicionar chave do YouTube.

---

## Como usar

### Buscar sinais de demanda

```bash
python -m src.main search --cards config/cards.yml --limit 20
```

Isso vai:
- Ler as cartas de `config/cards.yml`
- Buscar no **Reddit** e **Mercado Livre**
- Classificar cada resultado
- Salvar em `data/radar.db` e `data/radar_results.csv`
- Mostrar uma tabela com os melhores resultados

**Opções úteis:**

| Opção | Descrição |
|-------|-----------|
| `--limit 20` | Máximo de resultados por carta por fonte |
| `--mock` | Usar dados simulados (sem internet) |
| `--fallback-mock` | Se APIs falharem, usar mock automaticamente (padrão: ligado) |
| `--no-fallback-mock` | Desligar fallback automático para mock |
| `--sources config/sources.yml` | Arquivo de fontes |

**Exemplo com dados simulados (teste offline):**

```bash
python -m src.main search --mock --limit 5
```

### Ver relatório

```bash
python -m src.main report
```

Mostra estatísticas e os melhores resultados já salvos.

### Exportar CSV

```bash
python -m src.main export
```

Gera/atualiza `data/radar_results.csv` a partir do banco SQLite.

---

## Estrutura do projeto

```
radar-pokemon-brasil/
├── README.md
├── .env.example
├── requirements.txt
├── config/
│   ├── cards.yml          # Cartas monitoradas
│   ├── keywords.yml       # Palavras-chave de intenção
│   └── sources.yml        # Fontes habilitadas
├── src/
│   ├── main.py            # CLI principal
│   ├── models.py          # Modelos de dados
│   ├── database.py        # SQLite
│   ├── scoring.py         # Classificação e score
│   ├── normalizer.py      # Normalização de nomes
│   ├── exporters.py       # Exportação CSV
│   └── connectors/
│       ├── reddit.py
│       ├── mercado_livre.py
│       ├── youtube.py
│       └── discord_placeholder.py
├── data/
│   ├── radar_results.csv
│   └── radar.db
├── docs/
│   └── future_connectors_meta.md  # Facebook/Instagram (futuro)
└── tests/
    ├── test_scoring.py
    └── test_normalizer.py
```

---

## Fontes de dados

| Fonte | Status | Autenticação |
|-------|--------|--------------|
| **Reddit** | ✅ Ativo | User-Agent no `.env` (sem login) |
| **Mercado Livre** | ✅ Ativo | API pública, sem chave |
| **YouTube** | ⚙️ Opcional | `YOUTUBE_API_KEY` no `.env` |
| **Discord** | 📋 Placeholder | Importação manual futura |
| **Facebook/Instagram** | ❌ Futuro | Ver `docs/future_connectors_meta.md` |

### Reddit

Usa o endpoint JSON público (`reddit.com/search.json`).  
Se receber bloqueio (HTTP 429), aguarde alguns minutos ou use `--mock`.

Configure um User-Agent descritivo em `.env`:

```
REDDIT_USER_AGENT=RadarPokemonBrasil/1.0 (seu@email.com)
```

### Mercado Livre

Usa a [API pública de busca](https://developers.mercadolivre.com.br/pt_br/itens-e-buscas) do site MLB (Brasil).  
Não exige cadastro para buscas básicas.

### YouTube

Para habilitar, edite `config/sources.yml`:

```yaml
youtube:
  enabled: true
```

E adicione sua chave em `.env`:

```
YOUTUBE_API_KEY=sua_chave_aqui
```

Obtenha a chave em [Google Cloud Console](https://console.cloud.google.com/) → YouTube Data API v3.

---

## Classificação de intenção

| Tipo | Significado |
|------|-------------|
| `BUY_INTENT` | Provável comprador |
| `SELL_INTENT` | Provável vendedor |
| `PRICE_REFERENCE` | Anúncio/referência de preço |
| `DISCUSSION` | Conversa sem intenção clara |
| `UNKNOWN` | Incerto |

### Score (0–100)

| Faixa | Significado |
|-------|-------------|
| 90–100 | Compra explícita ("compro", "procuro", "WTB") |
| 70–89 | Compra provável ("alguém tem?", "onde acho?") |
| 40–69 | Menção relevante sem compra clara |
| 0–39 | Ruído ou discussão genérica |

---

## Personalizar cartas e palavras-chave

**Cartas** — edite `config/cards.yml`:

```yaml
cards:
  - Charizard
  - SuaCartaAqui
```

**Palavras-chave** — edite `config/keywords.yml` (compra/venda em PT e EN).

**Fontes** — edite `config/sources.yml` para habilitar/desabilitar conectores.

---

## Testes

```bash
pytest tests/ -v
```

---

## Conformidade e segurança

Este projeto segue estas regras:

- ✅ Apenas dados **públicos**
- ✅ APIs **oficiais** quando disponíveis
- ✅ Links salvos para **análise manual**
- ❌ Sem login automático em Facebook, Instagram, WhatsApp
- ❌ Sem scraping de grupos/servidores **privados**
- ❌ Sem envio automático de mensagens
- ❌ Sem burlar captcha, paywall ou autenticação

Leia mais sobre Facebook/Instagram em [`docs/future_connectors_meta.md`](docs/future_connectors_meta.md).

---

## Solução de problemas

| Problema | Solução |
|----------|---------|
| `ModuleNotFoundError: src` | Execute da pasta raiz do projeto |
| Reddit sem resultados | IPs de datacenter podem ser bloqueados; use `--mock` ou rode localmente |
| Mercado Livre 403 | Tente de rede residencial; o fallback mock cobre testes |
| YouTube não funciona | Normal — precisa de `YOUTUBE_API_KEY` |
| `pip install` falha | Verifique Python 3.11+ com `python3 --version` |

---

## Licença

Projeto de prova de conceito para validação de mercado. Use com responsabilidade e respeite os termos de cada plataforma.
