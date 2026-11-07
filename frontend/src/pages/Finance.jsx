import { useParams, useNavigate } from "react-router-dom";
import { LayoutDashboard, ArrowDownToLine, ArrowUpFromLine, Tags, Repeat, Target, Users, Landmark, Bot, Lock } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { RefDataProvider } from "@/components/finance/RefData";
import Overview from "@/components/finance/Overview";
import Transactions from "@/components/finance/Transactions";
import Categories from "@/components/finance/Categories";
import Recurring from "@/components/finance/Recurring";
import Budgets from "@/components/finance/Budgets";
import Technicians from "@/components/finance/Technicians";
import Banks from "@/components/finance/Banks";
import Assistants from "@/components/finance/Assistants";

const TABS = [
  { id: "visao-geral", label: "Visão Geral", Icon: LayoutDashboard, tech: true, el: () => <Overview /> },
  { id: "entradas", label: "Entradas", Icon: ArrowDownToLine, tech: true, el: () => <Transactions type="entrada" /> },
  { id: "saidas", label: "Saídas", Icon: ArrowUpFromLine, tech: true, el: () => <Transactions type="saida" /> },
  { id: "categorias", label: "Categorias", Icon: Tags, el: () => <Categories /> },
  { id: "despesas-fixas", label: "Despesas Fixas", Icon: Repeat, el: () => <Recurring /> },
  { id: "metas-limites", label: "Metas e Limites", Icon: Target, el: () => <Budgets /> },
  { id: "tecnicos", label: "Técnicos", Icon: Users, tech: true, el: () => <Technicians /> },
  { id: "bancos", label: "Bancos", Icon: Landmark, el: () => <Banks /> },
  { id: "assistentes", label: "Assistentes", Icon: Bot, el: () => <Assistants /> },
];

export default function Finance() {
  const { tab = "visao-geral" } = useParams();
  const navigate = useNavigate();
  const { isAdmin, hasFinance } = useAuth();

  if (!hasFinance) {
    return (
      <div className="max-w-xl mx-auto mt-20 p-8 text-center border border-slate-200 rounded-xl" data-testid="finance-blocked">
        <Lock className="mx-auto text-slate-400 mb-3" />
        <h1 className="text-xl font-semibold text-slate-900">Sem acesso ao Financeiro</h1>
        <p className="text-sm text-slate-500 mt-2">O seu cadastro não libera esta página. Fale com o administrador.</p>
      </div>
    );
  }

  const tabs = TABS.filter((t) => isAdmin || t.tech);
  const current = tabs.find((t) => t.id === tab) || tabs[0];

  return (
    <RefDataProvider>
      <div className="border-b border-slate-200 bg-white sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-5">
          <h1 className="text-3xl font-bold tracking-tight text-slate-900">Financeiro</h1>
          <p className="text-sm text-slate-500 mt-1">Quanto entrou, quanto saiu, quanto cada OS rendeu e quanto falta receber.</p>
          <div className="flex gap-1 mt-4 overflow-x-auto -mb-px" data-testid="finance-tabs">
            {tabs.map(({ id, label, Icon }) => (
              <button key={id} onClick={() => navigate(`/financeiro/${id}`)} data-testid={`tab-nav-${id}`}
                className={`flex items-center gap-2 px-3 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${current.id === id ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500 hover:text-slate-900"}`}>
                <Icon size={15} />{label}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="max-w-7xl mx-auto p-4 sm:p-6 lg:p-8 space-y-6 fade-up" key={current.id}>
        {current.el()}
      </div>
    </RefDataProvider>
  );
}
