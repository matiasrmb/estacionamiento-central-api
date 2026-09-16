CREATE TABLE IF NOT EXISTS gastos_operacion_auditoria (
    id_auditoria INT AUTO_INCREMENT PRIMARY KEY,
    id_gasto INT NOT NULL,
    accion VARCHAR(20) NOT NULL,
    usuario VARCHAR(50) NOT NULL,
    fecha_hora DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    snapshot_anterior TEXT NULL,
    snapshot_nuevo TEXT NULL,
    INDEX idx_gastos_operacion_auditoria_gasto (id_gasto),
    INDEX idx_gastos_operacion_auditoria_fecha (fecha_hora)
);
