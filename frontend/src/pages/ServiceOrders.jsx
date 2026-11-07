import { useEffect, useState, useCallback } from "react";
import { Plus, Wallet } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { api, errMsg } from "@/lib/api";
import { brl, fmtDate } from "@/lib/format";
import { useAuth } from "@/context/AuthContext";
import { Card, SimpleSelect, Empty } from "@/components/finance/common";
import OsModal from "@/components/OsModal";
import { toast } from "sonner";

const NewOs = ({ open, onClose, onSaved, techs }) => {
  const [f, setF] = useState({ client: "", technician_id: "", service_value: "", fee_value: "", part: "", part_qty: 1, part_price: "", part_cost: "" });
  const set = (k) => (e) => setF({ ...f, [k]: e.target ? e.target.value : e });
  const save = async () => {
    if (!f.client || !f.technician_id) return toast.error("Informe cliente e técnico");
    const parts = f.part ? [{ name: f.part, qty: Number(f.part_qty), unit_price: Number(f.part_price || 0), unit_cost: Number(f.part_cost || 0) }] : [];
    try {
      await api.post("/os", { client: f.client, technician_id: f.technician_id, service_value: Number(f.service_value || 0), fee_value: Number(f.fee_value || 0), parts });
      toast.success("OS criada");
      onSaved();
      onClose();
    } catch (e) { toast.error(errMsg(e)); }
  };
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="bg-white max-w-lg" data-testid="new-os-dialog">
        <DialogHeader><DialogTitle>Nova OS (simulada)</DialogTitle></DialogHeader>
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2 space-y-1.5"><Label className="text-xs">Cliente</Label><Input value={f.client} onChange={set("client")} data-testid="new-os-client" /></div>
          <div className="col-span-2 space-y-1.5"><Label className="text-xs">Técnico</Label><SimpleSelect className="w-full" value={f.technician_id} onChange={set("technician_id")} placeholder="Escolha" testId="new-os-technician" options={techs.map((t) => ({ value: t.id, label: t.name }))} /></div>
          <div className="space-y-1.5"><Label className="text-xs">Valor do serviço</Label><Input type="number" value={f.service_value} onChange={set("service_value")} data-testid="new-os-service" /></div>
          <div className="space-y-1.5"><Label className="text-xs">Taxa</Label><Input type="number" value={f.fee_value} onChange={set("fee_value")} data-testid="new-os-fee" /></div>
          <div className="col-span-2 space-y-1.5"><Label className="text-xs">Peça (opcional)</Label><Input value={f.part} onChange={set("part")} data-testid="new-os-part" /></div>
          <div className="space-y-1.5"><Label className="text-xs">Preço de venda da peça</Label><Input type="number" value={f.part_price} onChange={set("part_price")} data-testid="new-os-part-price" /></div>
          <div className="space-y-1.5"><Label className="text-xs">Custo da peça</Label><Input type="number" value={f.part_cost} onChange={set("part_cost")} data-testid="new-os-part-cost" /></div>
        </div>
        <DialogFooter><Button variant="outline" onClick={onClose}>Cancelar</Button><Button className="bg-blue-600 hover:bg-blue-700" onClick={save} data-testid="new-os-submit-btn">Criar OS</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default function ServiceOrders() {
  const { isAdmin } = useAuth();
  const [orders, setOrders] = useState([]);
  const [techs, setTechs] = useState([]);
  const [sel, setSel] = useState(null);
  const [newOpen, setNewOpen] = useState(false);

  const load = useCallback(async () => {
    const r = await api.get("/os");
    setOrders(r.data);
    setSel((s) => (s ? r.data.find((o) => o.id === s.id) || null : null));
  }, []);
  useEffect(() => {
    load();
    if (isAdmin) api.get("/users").then((r) => setTechs(r.data.filter((u) => u.role === "tecnico")));
  }, [load, isAdmin]);
  const techName = (id) => techs.find((t) => t.id === id)?.name || "";

  return (
    <div className="max-w-7xl mx-auto p-4 sm:p-6 lg:p-8 space-y-6 fade-up">
      <div className="flex flex-wrap justify-between items-end gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900">Ordens de Serviço</h1>
          <p className="text-sm text-slate-500 mt-1">Página simulada para demonstrar o vínculo com o Financeiro.</p>
        </div>
        {isAdmin && <Button className="bg-blue-600 hover:bg-blue-700" onClick={() => setNewOpen(true)} data-testid="new-os-btn"><Plus size={16} className="mr-1" />Nova OS</Button>}
      </div>
      <Card className="overflow-x-auto">
        {orders.length === 0 ? <Empty text="Nenhuma OS" /> : (
          <table className="w-full text-sm" data-testid="os-table">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr><th className="px-4 py-3 text-left">OS</th><th className="px-4 py-3 text-left">Cliente</th>{isAdmin && <th className="px-4 py-3 text-left">Técnico</th>}<th className="px-4 py-3 text-left">Status</th><th className="px-4 py-3 text-left">Concluída</th><th className="px-4 py-3 text-right">Total</th><th /></tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id} className="border-t border-slate-100 hover:bg-slate-50/60" data-testid={`os-row-${o.number}`}>
                  <td className="px-4 py-3 font-semibold">#{o.number}</td>
                  <td className="px-4 py-3">{o.client}</td>
                  {isAdmin && <td className="px-4 py-3">{techName(o.technician_id)}</td>}
                  <td className="px-4 py-3"><span className={`text-xs px-2.5 py-0.5 rounded-full font-semibold border ${o.status === "concluida" ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-blue-50 text-blue-700 border-blue-200"}`}>{o.status === "concluida" ? "Concluída" : "Aberta"}</span></td>
                  <td className="px-4 py-3 text-slate-600">{fmtDate(o.completed_at)}</td>
                  <td className="px-4 py-3 text-right font-mono-num font-semibold">{brl(o.total)}</td>
                  <td className="px-3 py-3 text-right"><Button size="sm" variant="outline" onClick={() => setSel(o)} data-testid={`os-finance-modal-btn-${o.id}`}><Wallet size={14} className="mr-1" />Abrir</Button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <OsModal os={sel} onClose={() => setSel(null)} onChanged={load} />
      <NewOs open={newOpen} onClose={() => setNewOpen(false)} onSaved={load} techs={techs} />
    </div>
  );
}
