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

# 4. Primeira busca de teste (funciona sem internet)
python3 -m src search --mock --limit 5

# 5. Ver relatório de mercado
python3 -m src report
```

No **Windows**, use `py -3` no lugar de `python3` se necessário, e ative com `.venv\Scripts\activate`.

**Atalho ainda mais fácil** (sem digitar `python3 -m src`):

| Sistema | Comando |
|---------|---------|
| Linux/Mac | `./radar.sh search --mock --limit 5` |
| Windows | `radar.bat search --mock --limit 5` |

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
python3 -m src.main search --cards config/cards.yml --limit 20 --no-mock
```
Sem fallback simulado. Se Reddit ou Mercado Livre falharem, a fonte retorna **zero resultados** e mostra um aviso amigável.

**Dados simulados (teste offline):**
```bash
python3 -m src.main search --mock --limit 5
```
Todos os resultados são marcados como `data_mode=mock`.

**Busca padrão (com fallback automático):**
```bash
python3 -m src.main search --limit 20
```
Tenta APIs reais primeiro; se falharem, usa mock automaticamente (útil para demonstração).

Atalhos:
```bash
./radar.sh search --no-mock --limit 20    # Linux/Mac
radar.bat search --mock --limit 5         # Windows
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

No **relatório**, o painel **"Modo dos dados"** mostra:
- quantos resultados são `live`, `mock` e `manual_import`
- um **aviso vermelho grande** se houver qualquer dado `mock`

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
| `python3 -m src.main search` | Busca sinais nas fontes configuradas |
| `python3 -m src.main search --no-mock` | Apenas dados reais (validação) |
| `python3 -m src.main search --mock` | Apenas dados simulados |
| `python3 -m src.main report` | Relatório de inteligência de mercado |
| `python3 -m src.main export` | Exporta CSV |
| `python3 -m src.main reset-db` | Apaga banco e CSV (com confirmação) |
| `python3 -m src.main test-mercadolivre` | Diagnostica API do Mercado Livre (não salva no banco) |
| `python3 -m src.main --help` | Lista todas as opções |

### Diagnosticar Mercado Livre

Se a busca real falhar, teste só o conector:

```bash
python3 -m src.main test-mercadolivre --query "carta pokemon charizard"
```

O comando mostra URL, status HTTP, trecho da resposta, se o JSON é válido e sugestões de correção — **sem gravar no banco**.

**Opções do search:**

| Opção | Descrição |
|-------|-----------|
| `--mock` | Apenas dados simulados (`data_mode=mock`) |
| `--no-mock` | Sem fallback mock se APIs falharem |
| `--limit 20` | Máximo por carta por fonte |

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
├── data/
│   ├── radar.db            # Banco (gerado automaticamente)
│   └── radar_results.csv   # Exportação CSV
└── tests/
```

---

## Fontes de dados

| Fonte | Status | Precisa de chave? |
|-------|--------|-------------------|
| Reddit | ✅ Ativo | Não (User-Agent opcional no `.env`) |
| Mercado Livre | ✅ Ativo | Não |
| YouTube | ⚙️ Opcional | Sim (`YOUTUBE_API_KEY`) |
| Discord | 📋 Futuro | Importação manual |
| Facebook/Instagram | ❌ Futuro | Ver `docs/future_connectors_meta.md` |

> **Nota:** APIs podem bloquear IPs de datacenter. Em casa costuma funcionar melhor. Se falhar, use `--mock` ou deixe o fallback automático ligado (padrão).

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
| Reddit/ML sem resultados com `--no-mock` | Normal em datacenter; rode de rede residencial |
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
