import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Wallet, ShieldCheck, Wrench, Ban } from "lucide-react";
import { api, errMsg } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";

const accessLabel = (u) => {
  if (u.role === "admin") return { text: "Admin · vê tudo", Icon: ShieldCheck };
  if (u.finance_access === "own") return { text: "Técnico · só os dados dele", Icon: Wrench };
  return { text: "Técnico · sem acesso ao financeiro", Icon: Ban };
};

export default function Login() {
  const [users, setUsers] = useState([]);
  const { login } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    api.get("/auth/demo-users").then((r) => setUsers(r.data));
  }, []);

  const enter = async (id) => {
    try {
      await login(id);
      navigate("/financeiro");
    } catch (e) {
      toast.error(errMsg(e));
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-white border border-slate-200 rounded-2xl shadow-sm p-8 fade-up" data-testid="login-card">
        <div className="flex items-center gap-3 mb-6">
          <div className="h-10 w-10 rounded-xl bg-blue-600 text-white flex items-center justify-center"><Wallet size={20} /></div>
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Financeiro</h1>
            <p className="text-xs text-slate-500">Acesso de demonstração (login simulado)</p>
          </div>
        </div>
        <p className="text-sm text-slate-600 mb-4">Escolha um perfil para entrar. As permissões são aplicadas no servidor.</p>
        <div className="space-y-2">
          {users.map((u) => {
            const { text, Icon } = accessLabel(u);
            return (
              <button key={u.id} onClick={() => enter(u.id)} data-testid={`login-user-${u.id}`}
                className="w-full flex items-center justify-between gap-3 border border-slate-200 rounded-xl px-4 py-3 text-left hover:border-blue-400 hover:bg-blue-50 transition-colors">
                <div>
                  <div className="font-semibold text-slate-900">{u.name}</div>
                  <div className="text-xs text-slate-500 flex items-center gap-1"><Icon size={12} /> {text}</div>
                </div>
                <span className="text-sm font-medium text-blue-600">Entrar</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
