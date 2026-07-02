CHARGED_WASH_ONLY_STATES = {"FINALIZADO_COBRADO"}


def build_accounting_summary(parking_movements, bathroom_uses, wash_only_operations):
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

    return {
        "total_recaudado": total_recaudado,
        "total_ingresos": len(parking_movements),
        "total_salidas": len(parking_movements),
        "total_banos": len(bathroom_uses),
        "total_banos_monto": total_banos_monto,
        "total_lavados_solos": len(charged_wash_only),
        "total_lavados_solos_monto": total_lavados_solos_monto,
        "total_general": total_recaudado + total_banos_monto + total_lavados_solos_monto,
    }


def build_report_totals(items, wash_only_operations):
    total_recaudado = _sum_amount(items, "tarifa_aplicada")
    charged_wash_only = [
        operation
        for operation in wash_only_operations
        if operation.get("estado") in CHARGED_WASH_ONLY_STATES
    ]
    total_lavados_solos_monto = _sum_amount(charged_wash_only, "valor_lavado_snapshot")

    return {
        "total_recaudado": total_recaudado,
        "total_movimientos": len(items),
        "total_lavados_solos": len(charged_wash_only),
        "total_lavados_solos_monto": total_lavados_solos_monto,
        "total_general": total_recaudado + total_lavados_solos_monto,
    }


def _sum_amount(rows, key):
    return sum(int(row.get(key) or 0) for row in rows)
