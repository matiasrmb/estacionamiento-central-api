ALTER TABLE cierres_diarios
    ADD COLUMN total_noches INT NOT NULL DEFAULT 0,
    ADD COLUMN total_noches_monto INT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS cobros_noches (
    id_cobro_noche INT AUTO_INCREMENT PRIMARY KEY,
    id_ingreso INT NOT NULL,
    monto_snapshot INT NOT NULL,
    hora_inicio_snapshot TIME NOT NULL,
    hora_fin_snapshot TIME NOT NULL,
    fecha_hora_pago DATETIME NOT NULL,
    usuario VARCHAR(50) NOT NULL,
    estado ENUM('PAGADO', 'ANULADO') NOT NULL DEFAULT 'PAGADO',
    estado_operativo ENUM('PENDIENTE', 'RETIRADO', 'CONVERTIDO') NOT NULL DEFAULT 'PENDIENTE',
    fecha_hora_resolucion DATETIME NULL,
    id_cierre INT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_cobros_noches_ingreso (id_ingreso),
    INDEX idx_cobros_noches_pendiente_cierre (id_cierre, fecha_hora_pago),
    INDEX idx_cobros_noches_estado_operativo (estado_operativo, id_ingreso),
    CONSTRAINT fk_cobros_noches_ingreso FOREIGN KEY (id_ingreso) REFERENCES ingresos(id_ingreso),
    CONSTRAINT fk_cobros_noches_cierre FOREIGN KEY (id_cierre) REFERENCES cierres_diarios(id_cierre)
);

INSERT INTO configuracion (clave, valor) VALUES
    ('noches_activo', '0'),
('noches_hora_inicio', '19:30'),
('noches_hora_fin', '09:30'),
    ('noches_valor', '0')
ON DUPLICATE KEY UPDATE clave = VALUES(clave);
