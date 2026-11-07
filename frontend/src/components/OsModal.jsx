import { useEffect, useState } from "react";
import { CheckCircle2 } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { api, errMsg } from "@/lib/api";
import { brl, fmtDate, METHODS, STATUSES } from "@/lib/format";
import { useAuth } from "@/context/AuthContext";
import { SimpleSelect, StatusBadge } from "@/components/finance/common";
import { toast } from "sonner";

const Stat = ({ id, label, value, tone = "text-slate-900" }) => (
  <div className="bg-slate-50 border border-slate-200 rounded-lg p-3" data-testid={`os-finance-${id}`}>
    <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
    <div className={`font-bold font-mono-num mt-0.5 ${tone}`}>{brl(value)}</div>
  </div>
);

const FinanceBlock = ({ fin }) => (
  <div className="space-y-3">
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
      <Stat id="cobrado" label="Cobrado" value={fin.cobrado} />
      <Stat id="recebido" label="Recebido" value={fin.recebido} tone="text-emerald-700" />
      <Stat id="custo" label="Custou" value={fin.custo} tone="text-rose-700" />
      <Stat id="lucro" label="Rendeu" value={fin.lucro} tone="text-blue-700" />
    </div>
    <div className="text-xs text-slate-500">Falta receber {brl(fin.a_receber)} · custo das peças {brl(fin.custo_pecas)} · saídas vinculadas {brl(fin.custo_saidas)}</div>
    <div className="border border-slate-200 rounded-lg divide-y divide-slate-100 text-sm">
      {fin.lancamentos.length === 0 && <div className="p-3 text-slate-500 text-center">Nenhum lançamento vinculado</div>}
      {fin.lancamentos.map((t) => (
        <div key={t.id} className="flex justify-between items-center gap-2 px-3 py-2">
          <span className="truncate">{fmtDate(t.date)} · {t.description}</span>
          <span className="flex items-center gap-2 shrink-0"><StatusBadge status={t.status} /><span className={`font-mono-num ${t.type === "entrada" ? "text-emerald-700" : "text-rose-700"}`}>{t.type === "entrada" ? "+" : "-"}{brl(t.amount / Math.max(t.os_ids.length, 1))}</span></span>
        </div>
      ))}
    </div>
  </div>
);

export default function OsModal({ os, onClose, onChanged }) {
  const { hasFinance } = useAuth();
  const [fin, setFin] = useState(null);
  const [method, setMethod] = useState("pix");
  const [status, setStatus] = useState("previsto");

  const loadFin = () => {
    if (!os || !hasFinance) return;
    api.get(`/os/${os.id}/finance`).then((r) => setFin(r.data)).catch(() => setFin(null));
  };
  useEffect(() => {
    setFin(null);
    loadFin();
  }, [os?.id, os?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const complete = async () => {
    try {
      await api.post(`/os/${os.id}/complete`, { payment_method: method, status });
      toast.success("OS concluída: entradas geradas no financeiro");
      onChanged();
    } catch (e) { toast.error(errMsg(e)); }
  };

  return (
    <Dialog open={!!os} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="bg-white max-w-2xl max-h-[90vh] overflow-y-auto" data-testid="os-modal">
        {os && (
          <>
            <DialogHeader><DialogTitle>OS #{os.number} · {os.client}</DialogTitle></DialogHeader>
            <div className="text-sm grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div><div className="text-xs text-slate-500">Serviço</div>{brl(os.service_value)}</div>
              <div><div className="text-xs text-slate-500">Taxa</div>{brl(os.fee_value)}</div>
              <div><div className="text-xs text-slate-500">Peças</div>{brl(os.parts.reduce((a, p) => a + p.qty * p.unit_price, 0))}</div>
              <div><div className="text-xs text-slate-500">Total</div><b>{brl(os.total)}</b></div>
            </div>
            {os.parts.length > 0 && <div className="text-xs text-slate-500">Peças: {os.parts.map((p) => `${p.qty}x ${p.name}`).join(", ")}</div>}
            <div className="border-t border-slate-200 pt-4">
              <h3 className="font-semibold text-slate-900 mb-3">Financeiro desta OS</h3>
              {!hasFinance && <div className="text-sm text-slate-500" data-testid="os-finance-blocked">Seu cadastro não libera o financeiro.</div>}
              {hasFinance && fin && <FinanceBlock fin={fin} />}
            </div>
            {os.status !== "concluida" && (
              <DialogFooter className="border-t border-slate-200 pt-4 flex-wrap gap-2 sm:justify-between">
                <div className="flex gap-2">
                  <SimpleSelect className="w-32" value={method} onChange={setMethod} testId="os-complete-method" options={Object.entries(METHODS).map(([value, label]) => ({ value, label }))} />
                  <SimpleSelect className="w-32" value={status} onChange={setStatus} testId="os-complete-status" options={Object.entries(STATUSES).filter(([k]) => k !== "atrasado").map(([value, label]) => ({ value, label }))} />
                </div>
                <Button className="bg-blue-600 hover:bg-blue-700" onClick={complete} data-testid="os-complete-btn"><CheckCircle2 size={16} className="mr-1" />Concluir OS</Button>
              </DialogFooter>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
