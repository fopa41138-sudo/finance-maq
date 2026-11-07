# PRD - Módulo Financeiro

## Original problem statement
Preciso criar um módulo financeiro. GUIA DO MÓDULO FINANCEIRO — Visão: responder, a qualquer momento, quanto entrou, quanto saiu, quanto cada OS rendeu e quanto falta receber. Layout: uma página "Financeiro" com abas no topo, no mesmo estilo visual claro da página de Ordens de Serviço.
FASE 1: Visão Geral, Entradas, Saídas, Categorias (lançamentos com data, valor, descrição, categoria, forma de pagamento cartão/Pix/dinheiro, status previsto/pago/em atraso; visões dia/semana/mês; filtros período/categoria/técnico; vínculo automático OS→entrada com serviço, taxa e peças; vínculo manual a uma ou várias OSs; venda de peça avulsa; modal da OS com cobrado/recebido/custo; categorias editáveis; dashboard com comparação ao período anterior, gráfico por categoria, a receber x recebido, ranking de técnicos).
FASE 2: Despesas Fixas (lança todo mês com aviso de vencimento), Metas e Limites (80%/100%), Técnicos (comissões, repasses, histórico), conciliação simples.
FASE 3: Bancos (Pluggy Open Finance, importar extrato e sugerir vínculo com OS por valor e data) e Assistentes de IA (começar com resumo semanal).
Regras: admin vê tudo; técnico vê só o dele ou nada conforme cadastro; bloqueio no servidor.
Usuário: Pluggy, sem testing agent (usuário testa), TEMA CLARO, BOTÕES AZUIS, FUNDO BRANCO E TEXTO PRETO.
Escolhas: Fases 1, 2 e 3; comissão = % do serviço por técnico; Pluggy sandbox; resumo com GPT-6 Luna, fallback Ollama (gpt-oss); OS/técnicos/login MOCKADOS.

## Architecture
- Backend FastAPI: core.py (db, JWT demo auth, scope, recorrência), routes_finance.py (OS mock, categorias, lançamentos, visão geral), routes_control.py (despesas fixas, limites, técnicos/repasses), routes_automation.py (Pluggy, assistentes IA), seed.py
- Frontend React: /login (picker), /os (mock OS + modal financeiro), /financeiro/:tab (9 abas)
- MongoDB collections: users, service_orders, categories, transactions, recurring, budgets, payouts, bank_items, bank_accounts, bank_transactions, assistants, assistant_runs

## Implemented (2026-11-07)
- All 3 phases, server-side access rules (admin all / técnico own / técnico none = 403)
- OS completion auto-creates entries (serviço, taxa, peças) linked to OS + técnico
- Pluggy sandbox connect + import + suggestions; AI weekly summary (GPT-6 Luna -> Ollama fallback)

## Backlog
- P1: weekly summary sent automatically (cron) / by email
- P1: Pluggy webhooks for automatic sync
- P2: second assistant "alertar despesas acima do normal"; export CSV/PDF
- P2: replace mocked login/OS with the real system integration
