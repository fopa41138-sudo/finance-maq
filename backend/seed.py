from datetime import datetime, timezone, timedelta
from core import db, new_id, now_iso

ADMIN_ID = "u-admin"
TECHS = [
    ("u-carlos", "Carlos Mendes", 30, "own"),
    ("u-juliana", "Juliana Rocha", 25, "own"),
    ("u-rafael", "Rafael Lima", 20, "none"),
]

CATEGORIES = [
    ("entrada", "servico", "Serviço", "#2563EB", "servico"),
    ("entrada", "peca", "Peças", "#16A34A", "peca"),
    ("entrada", "taxa", "Taxa de visita", "#D97706", "taxa"),
    ("entrada", "outros", "Outras entradas", "#9333EA", None),
    ("saida", "fixa", "Aluguel", "#E11D48", None),
    ("saida", "fixa", "Salários e comissões", "#4F46E5", "comissao"),
    ("saida", "variavel", "Combustível", "#0891B2", None),
    ("saida", "variavel", "Peças compradas", "#059669", None),
    ("saida", "outra", "Outras saídas", "#64748B", None),
]


def d(days_ago: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=days_ago)).isoformat()


async def seed():
    if await db.users.count_documents({}) > 0:
        return
    await db.users.insert_one({"id": ADMIN_ID, "name": "Administrador", "email": "fopa41138@gmail.com",
                               "role": "admin", "commission_pct": 0, "finance_access": "all"})
    for uid, name, pct, access in TECHS:
        await db.users.insert_one({"id": uid, "name": name, "email": None, "role": "tecnico",
                                   "commission_pct": pct, "finance_access": access})
    cats = {}
    for i, (typ, group, name, color, key) in enumerate(CATEGORIES):
        cid = new_id()
        cats[name] = cid
        await db.categories.insert_one({"id": cid, "type": typ, "group": group, "name": name, "color": color,
                                        "system_key": key, "order": i})

    from routes_finance import complete_os_entries
    orders = [
        ("1001", "Padaria Pão Quente", "u-carlos", 350, 80, [("Compressor 1/3 HP", 1, 420, 260)], 40, True),
        ("1002", "Clínica Bem Estar", "u-juliana", 280, 80, [("Capacitor 35uF", 2, 45, 18)], 32, True),
        ("1003", "Mercado Central", "u-carlos", 520, 0, [("Placa eletrônica", 1, 690, 410)], 20, True),
        ("1004", "Escritório Alves", "u-rafael", 180, 60, [], 12, True),
        ("1005", "Restaurante Sabor", "u-juliana", 450, 80, [("Motor ventilador", 1, 310, 170)], 5, True),
        ("1006", "Hotel Avenida", "u-carlos", 600, 80, [("Gás R410A (kg)", 3, 95, 52)], 2, True),
        ("1007", "Farmácia Vida", "u-juliana", 300, 80, [], 0, False),
        ("1008", "Academia Forte", "u-rafael", 400, 60, [("Sensor de temperatura", 1, 120, 55)], 0, False),
    ]
    for num, cli, tech, serv, fee, parts, ago, done in orders:
        os_doc = {"id": new_id(), "number": num, "client": cli, "technician_id": tech, "service_value": serv,
                  "fee_value": fee, "parts": [{"name": n, "qty": q, "unit_price": p, "unit_cost": c} for n, q, p, c in parts],
                  "status": "concluida" if done else "aberta", "created_at": d(ago + 3), "completed_at": d(ago) if done else None}
        await db.service_orders.insert_one(os_doc)
        if done:
            await complete_os_entries(os_doc, "pix" if ago % 2 else "cartao", "pago" if ago > 10 else "previsto")

    def tx(typ, ago, amount, desc, cat, method="pix", status="pago", tech=None, part=None):
        return {"id": new_id(), "type": typ, "date": d(ago), "amount": amount, "description": desc,
                "category_id": cats[cat], "payment_method": method, "status": status, "os_ids": [],
                "technician_id": tech, "part_name": part, "reconciled": False, "source": "manual",
                "recurring_id": None, "created_at": now_iso()}
    extra = [
        tx("entrada", 15, 160, "Venda avulsa de filtro", "Peças", "dinheiro", part="Filtro de ar"),
        tx("entrada", 4, 95, "Venda avulsa de controle remoto", "Peças", "cartao", part="Controle remoto universal"),
        tx("saida", 35, 420, "Combustível - frota", "Combustível", "cartao"),
        tx("saida", 9, 380, "Combustível - frota", "Combustível", "cartao"),
        tx("saida", 20, 900, "Compra de peças - distribuidora", "Peças compradas", "pix"),
        tx("saida", 6, 650, "Compra de gás refrigerante", "Peças compradas", "pix"),
        tx("saida", 3, 120, "Material de escritório", "Outras saídas", "dinheiro"),
    ]
    await db.transactions.insert_many(extra)

    for desc, amount, cat, day in [("Aluguel do galpão", 2500, "Aluguel", 10), ("Salário auxiliar", 1800, "Salários e comissões", 5)]:
        await db.recurring.insert_one({"id": new_id(), "description": desc, "amount": amount, "category_id": cats[cat],
                                       "day_of_month": day, "payment_method": "pix", "active": True, "created_at": now_iso()})
    for cat, limit in [("Combustível", 900), ("Peças compradas", 1800), ("Outras saídas", 500)]:
        await db.budgets.insert_one({"id": new_id(), "category_id": cats[cat], "monthly_limit": limit})
    await db.assistants.insert_one({"id": new_id(), "name": "Resumo da semana", "function": "resumo_semanal",
                                    "instructions": "Seja direto, destaque o que exige ação.", "active": True,
                                    "created_at": now_iso()})
