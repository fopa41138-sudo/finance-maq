import { NavLink, useNavigate } from "react-router-dom";
import { Wallet, ClipboardList, LogOut } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";

const linkCls = ({ isActive }) =>
  `flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${isActive ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:text-slate-900 hover:bg-slate-50"}`;

export default function Layout({ children }) {
  const { user, logout, isAdmin } = useAuth();
  const navigate = useNavigate();

  const exit = () => {
    logout();
    navigate("/login");
  };

  return (
    <div className="min-h-screen bg-white">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-3">
          <div className="flex items-center gap-4 sm:gap-8 min-w-0">
            <div className="flex items-center gap-2 shrink-0">
              <div className="h-8 w-8 rounded-lg bg-blue-600 text-white flex items-center justify-center"><Wallet size={16} /></div>
              <span className="font-heading font-bold text-slate-900 hidden sm:inline">Gestão OS</span>
            </div>
            <nav className="flex items-center gap-1">
              <NavLink to="/os" className={linkCls} data-testid="nav-os"><ClipboardList size={16} /><span className="hidden sm:inline">Ordens de Serviço</span><span className="sm:hidden">OS</span></NavLink>
              <NavLink to="/financeiro" className={linkCls} data-testid="nav-financeiro"><Wallet size={16} />Financeiro</NavLink>
            </nav>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            <div className="text-right hidden md:block" data-testid="current-user">
              <div className="text-sm font-semibold text-slate-900">{user?.name}</div>
              <div className="text-xs text-slate-500">{isAdmin ? "Administrador" : "Técnico"}</div>
            </div>
            <Button variant="outline" size="sm" onClick={exit} data-testid="user-role-selector">
              <LogOut size={14} className="mr-1" /> Trocar perfil
            </Button>
          </div>
        </div>
      </header>
      <main>{children}</main>
    </div>
  );
}
