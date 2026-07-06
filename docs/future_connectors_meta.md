# Conectores futuros — Facebook e Instagram

## Status: NÃO IMPLEMENTADO no MVP

Facebook e Instagram **não** possuem conectores automatizados nesta versão do Radar Pokémon Brasil. Esta decisão é intencional e baseada em requisitos de conformidade e segurança.

## Por que não automatizar agora?

1. **Termos de uso da Meta** — Automação não autorizada de login, scraping de grupos ou coleta de dados pessoais viola os Termos de Serviço da Meta (Facebook/Instagram).
2. **APIs oficiais** — A Meta oferece APIs oficiais (Graph API, Marketing API) que exigem:
   - Aprovação de app na Meta for Developers
   - Permissões específicas por tipo de dado
   - Revisão de conformidade para dados de usuários
3. **Grupos privados** — Muitos grupos de compra/venda de cartas Pokémon são privados. Acessá-los sem autorização explícita é antiético e potencialmente ilegal.
4. **Risco legal (LGPD)** — Coleta automatizada de dados pessoais sem base legal adequada pode violar a Lei Geral de Proteção de Dados.

## Abordagem recomendada para o futuro

### Opção 1: API oficial da Meta (Graph API)

- Criar app em [developers.facebook.com](https://developers.facebook.com)
- Solicitar permissões `pages_read_engagement` ou equivalentes
- Usar apenas para **Páginas públicas** autorizadas
- Documentação: [Meta Graph API](https://developers.facebook.com/docs/graph-api)

### Opção 2: Importação manual

- Exportar posts/comentários relevantes manualmente
- Importar via JSON/CSV (similar ao conector Discord placeholder)
- Analisar com o pipeline de scoring existente

### Opção 3: Monitoramento de hashtags públicas

- Apenas via API oficial com permissões adequadas
- Limitado a conteúdo público explicitamente acessível

## O que o MVP faz em vez disso

O Radar Pokémon Brasil foca em fontes **públicas e acessíveis via API oficial ou endpoint permitido**:

| Fonte          | Status MVP      | Método                          |
|----------------|-----------------|---------------------------------|
| Reddit         | ✅ Implementado | API JSON pública                |
| Mercado Livre  | ✅ Implementado | API pública de busca            |
| YouTube        | ⚙️ Opcional     | YouTube Data API v3 (com chave) |
| Discord        | 📋 Placeholder  | Importação manual / bot futuro  |
| Facebook       | ❌ Futuro       | API oficial ou importação       |
| Instagram      | ❌ Futuro       | API oficial ou importação       |
| WhatsApp       | ❌ Nunca        | Proibido — sem API pública      |

## Regras que devem ser mantidas

- ❌ Não criar robôs de login automático
- ❌ Não burlar captcha, paywall ou autenticação
- ❌ Não enviar mensagens automáticas para leads
- ❌ Não fazer scraping de grupos/servidores privados
- ✅ Coletar apenas informações públicas
- ✅ Salvar links para análise manual
- ✅ Respeitar robots.txt e termos de uso
