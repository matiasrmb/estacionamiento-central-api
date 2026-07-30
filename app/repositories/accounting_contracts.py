CHARGED_WASH_ONLY_STATES = {"FINALIZADO_COBRADO"}


def build_accounting_summary(
    parking_movements,
    bathroom_uses,
    wash_only_operations,
    expenses=None,
    monthly_payments=None,
    night_charges=None,
):
    """Build the accounting shape shared by cierres and reports.

    Parking totals already include parking-linked washes. Solo wash revenue is
    reported separately only when it was charged immediately.
    """
    total_recaudado = _sum_amount(parking_movements, "tarifa_aplicada")
    total_banos_monto = _sum_amount(bathroom_uses, "monto")
    charged_wash_only = [
        operation
        for operation in wash_only_operations
        if operation.get("estado") in CHARGED_WASH_ONLY_STATES
    ]
    total_lavados_solos_monto = _sum_amount(charged_wash_only, "valor_lavado_snapshot")
    monthly_payments = monthly_payments or []
    total_mensualidades_monto = _sum_amount(monthly_payments, "monto_snapshot")
    night_charges = night_charges or []
    total_noches_monto = _sum_amount(night_charges, "monto_snapshot")
    total_general = (
        total_recaudado
        + total_banos_monto
        + total_lavados_solos_monto
        + total_mensualidades_monto
        + total_noches_monto
    )
    total_gastos = _sum_amount(expenses or [], "monto")

    return {
        "total_recaudado": total_recaudado,
        "total_ingresos": len(parking_movements),
        "total_salidas": len(parking_movements),
        "total_banos": len(bathroom_uses),
        "total_banos_monto": total_banos_monto,
        "total_lavados_solos": len(charged_wash_only),
        "total_lavados_solos_monto": total_lavados_solos_monto,
        "total_mensualidades": len(monthly_payments),
        "total_mensualidades_monto": total_mensualidades_monto,
        "total_noches": len(night_charges),
        "total_noches_monto": total_noches_monto,
        "total_general": total_general,
        "total_gastos": total_gastos,
        "total_neto": total_general - total_gastos,
    }


def build_report_totals(items, wash_only_operations, monthly_payments=None, night_charges=None):
    total_recaudado = _sum_amount(items, "tarifa_aplicada")
    charged_wash_only = [
        operation
        for operation in wash_only_operations
        if operation.get("estado") in CHARGED_WASH_ONLY_STATES
    ]
    total_lavados_solos_monto = _sum_amount(charged_wash_only, "valor_lavado_snapshot")
    monthly_payments = monthly_payments or []
    total_mensualidades_monto = _sum_amount(monthly_payments, "monto_snapshot")
    night_charges = night_charges or []
    total_noches_monto = _sum_amount(night_charges, "monto_snapshot")

    return {
        "total_recaudado": total_recaudado,
        "total_movimientos": len(items),
        "total_lavados_solos": len(charged_wash_only),
        "total_lavados_solos_monto": total_lavados_solos_monto,
        "total_mensualidades": len(monthly_payments),
        "total_mensualidades_monto": total_mensualidades_monto,
        "total_noches": len(night_charges),
        "total_noches_monto": total_noches_monto,
        "total_general": (
            total_recaudado
            + total_lavados_solos_monto
            + total_mensualidades_monto
            + total_noches_monto
        ),
    }


def _sum_amount(rows, key):
    return sum(int(row.get(key) or 0) for row in rows)
