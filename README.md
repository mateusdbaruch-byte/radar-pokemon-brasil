# Radar Pokémon Brasil 🇧🇷

Ferramenta de **inteligência de mercado** para cartas Pokémon TCG no Brasil.  
Coleta sinais públicos de compra e venda, calcula preços e gera recomendações simples por carta.

---

## O que este projeto faz?

1. Monitora cartas Pokémon (Charizard, Umbreon, Pikachu…)
2. Busca menções em fontes públicas (Reddit, Mercado Livre…)
3. Classifica intenção de compra ou venda
4. Calcula **preço mínimo, máximo e médio** por carta
5. Gera recomendação: *boa demanda*, *muita oferta*, *possível oportunidade*, etc.
6. Salva em SQLite e CSV

> Este MVP **não** envia mensagens nem acessa grupos privados. Apenas coleta dados públicos.

---

## Guia rápido (copie e cole)

Se você já tem Python instalado, siga estes 5 passos na pasta do projeto:

```bash
# 1. Criar ambiente virtual
python3 -m venv .venv

# 2. Ativar (Linux/Mac)
source .venv/bin/activate

# 3. Instalar
pip install -r requirements.txt

# 4. Primeiro teste — diagnóstico do ambiente
python3 -m src.main doctor

# 5. Demonstração rápida com dados simulados
python3 -m src.main search --mock-only --limit 5

# 6. Ver relatório de mercado
python3 -m src.main report
```

No **Windows**, use `py -3` no lugar de `python3` se necessário, e ative com `.venv\Scripts\activate`.

**Atalho ainda mais fácil** (sem digitar `python3 -m src`):

| Sistema | Comando |
|---------|---------|
| Linux/Mac | `./radar.sh doctor` |
| Windows | `radar.bat doctor` |

---

## Primeira validação real (recomendado)

O MVP **não depende do Reddit**. Fluxo recomendado:

### 1. Preços reais via importação manual (LigaPokemon / MYP)

```bash
python3 -m src.main validate-import data/imports/manual_prices_example.csv
python3 -m src.main import-prices data/imports/manual_prices_example.csv
python3 -m src.main market-snapshot
```

### 2. Mercado Livre (quando disponível)

```bash
python3 -m src.main test-mercadolivre
python3 -m src.main search --sources mercado_livre --live-only --limit 20
python3 -m src.main report
```

### 3. Reddit — fonte opcional (após aprovação da API)

```bash
python3 -m src.main setup-env
python3 -m src.main reddit-policy-status
python3 -m src.main test-reddit-auth
```

Se `PENDING_APPROVAL`, o Reddit fica desabilitado até credenciais **e** aprovação oficial. Use `import-prices` enquanto isso.

```bash
python3 -m src.main search-reddit --query "pokemon tcg brasil" --limit 10
```

### 4. Diagnóstico geral

```bash
python3 -m src.main doctor
```

O `doctor` só falha criticamente se banco, CSV ou configs estiverem quebrados. Reddit em `PENDING_APPROVAL` é aviso, não erro do sistema.

---

## Primeiro teste (diagnóstico)

```bash
python3 -m src.main doctor
```

O `doctor` verifica Mercado Livre, Reddit, SQLite, CSV, `.env` e arquivos de config.

**Busca apenas com dados reais (todas as fontes):**

```bash
python3 -m src.main reset-db --force
python3 -m src.main search --cards config/cards.yml --limit 20 --live-only
python3 -m src.main report
```

**Demonstração com mock (offline):**

```bash
python3 -m src.main reset-db --force
python3 -m src.main search --cards config/cards.yml --limit 20 --mock-only
python3 -m src.main report
```

Guia completo: [`docs/VALIDACAO_DADOS_REAIS.md`](docs/VALIDACAO_DADOS_REAIS.md)

---

## Instalação detalhada (passo a passo para iniciantes)

### Passo 0 — Instalar o Python

1. Acesse [python.org/downloads](https://www.python.org/downloads/)
2. Baixe a versão **3.11 ou superior**
3. Durante a instalação no Windows, **marque** a opção **"Add Python to PATH"**
4. Confirme no terminal:
   ```bash
   python3 --version
   ```
   Deve aparecer algo como `Python 3.11.x` ou `Python 3.12.x`

   > **Windows:** se `python3` não funcionar, tente `py -3 --version`

### Passo 1 — Abrir o terminal na pasta do projeto

- **Windows:** clique com botão direito na pasta → "Abrir no Terminal" (ou PowerShell)
- **Mac:** Terminal → `cd` até a pasta do projeto
- **Linux:** Terminal → `cd radar-pokemon-brasil`

### Passo 2 — Criar ambiente virtual

Um "ambiente virtual" isola as dependências do projeto. Rode **uma vez**:

```bash
python3 -m venv .venv
```

Windows (se `python3` falhar):

```bash
py -3 -m venv .venv
```

### Passo 3 — Ativar o ambiente virtual

**Linux/Mac:**
```bash
source .venv/bin/activate
```

**Windows (Prompt de Comando):**
```bash
.venv\Scripts\activate
```

**Windows (PowerShell):**
```powershell
.venv\Scripts\Activate.ps1
```

Quando ativado, o terminal mostra `(.venv)` no início da linha.

### Passo 4 — Instalar dependências

```bash
pip install -r requirements.txt
```

### Passo 5 — (Opcional) Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Edite `.env` apenas se quiser personalizar o Reddit ou habilitar YouTube.

---

## Como usar

### Buscar sinais

**Dados reais (validação de mercado — recomendado):**
```bash
python3 -m src.main search --cards config/cards.yml --limit 20 --live-only
```
Sem fallback simulado. Se Reddit ou Mercado Livre falharem, a fonte retorna **zero resultados** e mostra um aviso amigável.

**Dados simulados (teste offline / demonstração):**
```bash
python3 -m src.main search --mock-only --limit 5
```
Todos os resultados são marcados como `data_mode=mock`.

**Busca padrão (com fallback automático):**
```bash
python3 -m src.main search --limit 20
```
Equivalente a `--allow-mock`: tenta APIs reais primeiro; se falharem, usa mock automaticamente.

Atalhos:
```bash
./radar.sh search --live-only --limit 20    # Linux/Mac
radar.bat search --mock-only --limit 5      # Windows
```

### Limpar o banco antes de uma nova validação

```bash
python3 -m src.main reset-db
```
Pede confirmação antes de apagar `data/radar.db` e `data/radar_results.csv`.

Sem confirmação (scripts automatizados):
```bash
python3 -m src.main reset-db --force
```

### Ver relatório de inteligência de mercado

```bash
python3 -m src.main report
```

### Como saber se os dados são reais ou simulados

Cada resultado tem o campo **`data_mode`**:

| Valor | Significado |
|-------|-------------|
| `live` | Coletado de API pública real (Reddit, Mercado Livre…) |
| `mock` | Dado simulado — **não use para decisão de mercado** |
| `manual_import` | Importado manualmente (ex.: exportação Discord) |

No **relatório**, a seção **VALIDAÇÃO DOS DADOS** (no topo) mostra:
- quantos resultados são `live`, `mock` e `manual_import`
- quantas fontes falharam na última busca
- um **aviso vermelho** se houver qualquer dado `mock`

No **CSV** (`data/radar_results.csv`), a coluna `data_mode` indica a origem de cada linha.

**Regra prática:** só confie no relatório para decisões se **live > 0** e **mock = 0**.

---

### Relatório — estrutura

#### 1. Resumo executivo
Visão geral do mercado monitorado: quantas cartas têm dados, total de sinais de compra/venda, anúncios e qual carta tem maior demanda.

#### 2. Destaques de mercado
Painéis interpretativos das cartas mais relevantes, com frases como:
> *"2 sinal(is) de compra (demanda média 93/100); 1 anúncio(s); preço médio R$ 149,90. Possível oportunidade — há demanda e anúncios ao mesmo tempo."*

#### 3. Inteligência por carta
Tabela consolidada com todas as cartas de `config/cards.yml`:

| Métrica | Descrição |
|---------|-----------|
| **Preço mín.** | Menor preço encontrado nos anúncios |
| **Preço máx.** | Maior preço encontrado |
| **Preço méd.** | Média dos preços com valor |
| **Anúncios** | Listagens no Mercado Livre e referências de preço |
| **Compra** | Sinais com intenção de compra (`BUY_INTENT`) |
| **Venda** | Sinais de venda e anúncios de marketplace |
| **Demanda** | Score médio dos compradores (0–100); `—` se não houver |
| **Fonte** | Principal origem dos dados (Reddit, Mercado Livre…) |
| **Recomendação** | Leitura simples do cenário (ver abaixo) |

Cartas sem dados aparecem com recomendação `dados insuficientes`.

#### 4. Top sinais individuais
Os posts/anúncios com maior score — detalhe complementar para análise manual.

**Recomendações possíveis:**

| Recomendação | Significado |
|--------------|-------------|
| `boa demanda` | Compradores ativos superam a oferta |
| `possível oportunidade` | Demanda e oferta coexistem — pode haver negócio |
| `muita oferta` | Muitos anúncios, pouca procura |
| `observar` | Sinais mistos — colete mais dados |
| `dados insuficientes` | Poucos sinais para concluir algo |

### Exportar CSV

```bash
python3 -m src export
```

Arquivo gerado: `data/radar_results.csv` (abre no Excel ou Google Sheets)

---

## Comandos disponíveis

| Comando | O que faz |
|---------|-----------|
| `python3 -m src.main setup-env` | Cria `.env` a partir do exemplo |
| `python3 -m src.main reddit-policy-status` | Status de política/aprovação Reddit |
| `python3 -m src.main search-reddit` | Busca apenas Reddit (live) |
| `python3 -m src.main validate-import` | Valida CSV de preços manuais |
| `python3 -m src.main import-prices` | Importa LigaPokemon/MYP (manual_import) |
| `python3 -m src.main market-snapshot` | Snapshot live + manual (sem mock) |
| `python3 -m src.main doctor` | Diagnóstico geral |
| `python3 -m src.main source-status` | Último status de cada conector |
| `python3 -m src.main search` | Busca nas fontes configuradas |
| `python3 -m src.main search --sources reddit` | Busca só Reddit |
| `python3 -m src.main search --live-only` | Apenas dados reais |
| `python3 -m src.main search --mock-only` | Apenas dados simulados |
| `python3 -m src.main report` | Relatório de inteligência de mercado |
| `python3 -m src.main export` | Exporta CSV |
| `python3 -m src.main reset-db` | Apaga banco e CSV |
| `python3 -m src.main test-mercadolivre` | Diagnóstico ML (não grava anúncios) |
| `python3 -m src.main test-reddit` | Diagnóstico Reddit |
| `python3 -m src.main --help` | Lista todas as opções |

### Diagnosticar Mercado Livre

Se a busca real falhar, teste só o conector:

```bash
python3 -m src.main test-mercadolivre --query "carta pokemon charizard"
```

O comando mostra URL, status HTTP, trecho da resposta e sugestões — salva o diagnóstico em `connector_health` (não grava `radar_results`).

### Diagnosticar Reddit

```bash
python3 -m src.main test-reddit --query "pokemon tcg brasil charizard"
```

Mostra método (GET), URL, modo (OAuth/público), status HTTP e preview da resposta — salva em `connector_health`.

Subreddit opcional:
```bash
python3 -m src.main test-reddit -q "charizard" --subreddit PokemonTCG
```

**Opções do search:**

| Opção | Descrição |
|-------|-----------|
| `--live-only` | Apenas dados reais; sem fallback mock |
| `--allow-mock` | Padrão — permite mock se APIs falharem |
| `--mock-only` | Apenas dados simulados (`data_mode=mock`) |
| `--sources reddit` | Filtra fontes (reddit, mercado_livre, youtube) |
| `--sources-config` | Caminho do YAML de fontes (padrão: config/sources.yml) |

---

## Estrutura do projeto

```
radar-pokemon-brasil/
├── radar.sh / radar.bat    # Atalhos para rodar sem digitar python
├── README.md
├── requirements.txt
├── pyproject.toml
├── config/
│   ├── cards.yml           # Cartas monitoradas
│   ├── keywords.yml        # Palavras-chave PT/EN
│   └── sources.yml         # Fontes habilitadas
├── src/
│   ├── main.py             # CLI
│   ├── market_intelligence.py  # Cálculo de métricas por carta
│   ├── reporting.py        # Relatório visual no terminal
│   ├── scoring.py          # Classificação de intenção
│   └── connectors/         # Reddit, Mercado Livre, etc.
├── docs/
│   ├── VALIDACAO_DADOS_REAIS.md  # Guia de validação live vs mock
│   └── future_connectors_meta.md
├── data/
│   ├── radar.db            # Banco (gerado automaticamente)
│   └── radar_results.csv   # Exportação CSV
└── tests/
```

---

## Fontes de dados

| Fonte | Status | Precisa de chave? |
|-------|--------|-------------------|
| Reddit | ⏳ Opcional | Requer aprovação API — `reddit-policy-status` |
| Mercado Livre | ⚙️ Diagnóstico | API pública; 403 comum — não trava MVP |
| LigaPokemon / MYP | ✅ Import manual | `import-prices` (manual_import) |
| YouTube | ⚙️ Opcional | Sim (`YOUTUBE_API_KEY`) |
| Discord | 📋 Futuro | Importação manual |
| Facebook/Instagram | ❌ Futuro | Ver `docs/future_connectors_meta.md` |

> **Nota:** APIs podem bloquear IPs de datacenter (HTTP 403). Rode `doctor` primeiro. Em rede residencial costuma funcionar melhor. Use `--mock-only` apenas para demonstração.

---

## Personalizar

**Cartas** — edite `config/cards.yml`:
```yaml
cards:
  - Charizard
  - SuaCartaAqui
```

**Palavras-chave** — `config/keywords.yml`  
**Fontes** — `config/sources.yml`

---

## Testes

```bash
python3 -m pytest tests/ -v
```

---

## Solução de problemas

| Problema | Solução |
|----------|---------|
| `python3: command not found` | Use `py -3` (Windows) ou instale Python |
| `ModuleNotFoundError: src` | Execute da **pasta raiz** do projeto |
| `pip: command not found` | Use `python3 -m pip install -r requirements.txt` |
| `Permission denied: ./radar.sh` | Rode `chmod +x radar.sh` |
| Reddit/ML sem resultados com `--live-only` | Normal em datacenter; rode `doctor` e teste em rede residencial |
| HTTP 403 no doctor | Bloqueio da API — não é dado real; veja `docs/VALIDACAO_DADOS_REAIS.md` |
| Relatório com aviso vermelho | Há dados `mock` — não use para decisão de mercado |
| Quer zerar histórico acumulado | `python3 -m src.main reset-db` |
| PowerShell bloqueia ativação | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Banco vazio no report | Execute `search` antes do `report` |

---

## Conformidade

- ✅ Apenas dados públicos via APIs oficiais
- ❌ Sem login automático em redes sociais
- ❌ Sem scraping de grupos privados
- ❌ Sem envio automático de mensagens

---

## Licença

Projeto de prova de conceito. Use com responsabilidade e respeite os termos de cada plataforma.
