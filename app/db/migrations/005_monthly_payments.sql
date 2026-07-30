ALTER TABLE vehiculos
    ADD COLUMN IF NOT EXISTS dia_vencimiento TINYINT UNSIGNED NOT NULL DEFAULT 1;

ALTER TABLE cierres_diarios
    ADD COLUMN IF NOT EXISTS total_mensualidades INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS total_mensualidades_monto INT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS pagos_mensuales (
    id_pago_mensual INT AUTO_INCREMENT PRIMARY KEY,
    id_vehiculo INT NOT NULL,
    periodo DATE NOT NULL,
    dia_vencimiento_snapshot TINYINT UNSIGNED NOT NULL,
    monto_snapshot INT NOT NULL,
    fecha_pago DATETIME NOT NULL,
    usuario VARCHAR(50) NOT NULL,
    metodo_pago VARCHAR(40) NULL,
    observacion VARCHAR(500) NULL,
    id_cierre INT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_pagos_mensuales_vehiculo_periodo (id_vehiculo, periodo),
    INDEX idx_pagos_mensuales_pendiente_cierre (id_cierre, fecha_pago),
    INDEX idx_pagos_mensuales_periodo (periodo),
    CONSTRAINT fk_pagos_mensuales_vehiculo FOREIGN KEY (id_vehiculo) REFERENCES vehiculos(id_vehiculo),
    CONSTRAINT fk_pagos_mensuales_cierre FOREIGN KEY (id_cierre) REFERENCES cierres_diarios(id_cierre)
);
