# Deploy no Replit — Radar Pokémon Brasil

Guia passo a passo para leigos: importar o projeto, configurar secrets e usar o app pelo navegador — **sem terminal complicado** e **sem port forwarding**.

---

## O que você vai ter no final

- Um **link público** (ex.: `https://seu-app.replit.app`) abrindo a dashboard
- Botões para ver oportunidades, Card Radar, orçamento e performance
- Botão **Rodar Radar Manualmente** para buscar novas oportunidades
- Tudo no mesmo ambiente: agente Python + dashboard Streamlit + banco SQLite

---

## Passo 1 — Criar conta no Replit

1. Acesse [https://replit.com](https://replit.com) e crie uma conta (grátis para começar).
2. Faça login.

---

## Passo 2 — Importar o projeto do GitHub

1. No Replit, clique em **Create Repl** (ou **+**).
2. Escolha **Import from GitHub**.
3. Cole a URL do repositório:

   ```
   https://github.com/mateusdbaruch-byte/radar-pokemon-brasil
   ```

4. Se pedir branch, use: `cursor/replit-webapp-6ae9` (ou `main` se já estiver mergeado).
5. Linguagem: **Python**.
6. Clique em **Import**.

O Replit vai clonar o código automaticamente.

---

## Passo 3 — Configurar Secrets (chave SerpAPI)

A chave **nunca** vai no código nem no GitHub. Use os Secrets do Replit:

1. No painel do Repl, abra a aba **Secrets** (ícone de cadeado).
2. Adicione estas variáveis:

| Nome | Valor | Obrigatório |
|------|-------|-------------|
| `SERPAPI_KEY` | Sua chave em [serpapi.com](https://serpapi.com) | Sim (para rodar o radar) |
| `WEB_SEARCH_PROVIDER` | `serpapi` | Recomendado |
| `SERPAPI_DAILY_BUDGET` | `20` | Opcional |
| `SERPAPI_MONTHLY_BUDGET` | `250` | Opcional |

3. Salve. O Replit injeta essas variáveis no ambiente — o app lê via `os.getenv`, igual ao `.env` local.

> **Sem `SERPAPI_KEY`:** o app abre normalmente, mas o botão *Rodar Radar* mostra um aviso amigável. A dashboard continua lendo o SQLite sem chamar a API ao abrir.

---

## Passo 4 — Rodar o app

O arquivo `.replit` já está configurado. Basta:

1. Clicar no botão **Run** (▶) no topo do Replit.
2. Aguardar a instalação das dependências (`requirements.txt`).
3. O Streamlit sobe automaticamente com:

   ```
   streamlit run src/dashboard/app.py --server.address 0.0.0.0 --server.port 8501
   ```

**Alternativa pelo Shell do Replit:**

```bash
pip install -r requirements.txt
python -m src.main webapp
```

---

## Passo 5 — Abrir o link público

1. Quando o app estiver rodando, o Replit mostra uma **URL de preview** (janela Webview ou link no painel).
2. Clique para abrir no navegador — é o seu app público.
3. Para deploy permanente: **Deployments** → publique o Repl (plano pago pode ser necessário para always-on).

Compartilhe esse link com quem for usar o radar — não precisa instalar Python.

---

## Passo 6 — Usar o app (sem programar)

1. Abra o link do app.
2. Na página **Início**, clique em **Rodar Radar Manualmente**.
3. Aguarde o scan (pode levar alguns minutos).
4. Clique em **Ver oportunidades** → **Opportunity Inbox**.
5. Clique em **Ver Card Radar** para análise por carta.
6. Revise links e evidências antes de agir.

---

## Passo 7 — Manter o projeto ajustável pela IA

### No Replit (com IA integrada)

- Use o **AI Assistant** do Replit para editar arquivos YAML em `config/` (cartas, perfis, domínios).
- Peça para a IA: *"Adicione a carta Pikachu na watchlist"* ou *"Ajuste o orçamento diário para 15"*.

### No Cursor (desenvolvimento avançado)

1. Clone o mesmo repositório GitHub no Cursor.
2. Faça alterações e push para uma branch.
3. No Replit: **Version control** → **Pull** para sincronizar.

### Arquivos que a IA pode ajustar com segurança

| Arquivo | O que muda |
|---------|------------|
| `config/watchlist.yml` | Cartas monitoradas |
| `config/search_profiles.yml` | Perfis e templates de busca |
| `config/blocked_domains.yml` | Domínios bloqueados |
| `config/cards.yml` | Lista de cartas do projeto |

**Não commite:** `.env`, `data/radar.db` (dados locais), chaves API.

---

## Solução de problemas

| Problema | O que fazer |
|----------|-------------|
| App não abre | Clique **Run** de novo; veja o Console por erros |
| `ModuleNotFoundError` | No Shell: `pip install -r requirements.txt` |
| Radar não roda | Verifique `SERPAPI_KEY` em Secrets |
| Orçamento esgotado | Normal — o app para com segurança; tente amanhã ou aumente `SERPAPI_DAILY_BUDGET` |
| Dashboard vazia | Rode o radar pelo botão na página Início |
| Repl “dorme” (plano grátis) | Abra o link e clique Run de novo |

---

## Segurança

- ✅ `SERPAPI_KEY` só em Secrets / variáveis de ambiente
- ✅ `.env` está no `.gitignore`
- ✅ Dashboard **não** chama SerpAPI ao abrir — só ao clicar em Rodar Radar
- ❌ Nunca cole a chave no código, README ou chat público

---

## Comandos úteis (opcional — Shell do Replit)

```bash
python -m src.main webapp              # inicia dashboard
python -m src.main run-daily-radar     # radar pelo terminal
python -m src.main opportunity-inbox   # lista no terminal
python -m pytest tests/ -q             # testes
```

A CLI completa continua disponível para quem quiser usar o terminal.
