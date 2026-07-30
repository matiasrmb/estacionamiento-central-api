CREATE TABLE IF NOT EXISTS gastos_operacion (
    id_gasto INT AUTO_INCREMENT PRIMARY KEY,
    fecha_hora DATETIME NOT NULL,
    categoria VARCHAR(50) NOT NULL,
    descripcion VARCHAR(500) NOT NULL,
    monto INT NOT NULL,
    usuario VARCHAR(50) NOT NULL,
    id_cierre INT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_gastos_operacion_pendiente (id_cierre, fecha_hora),
    INDEX idx_gastos_operacion_cierre (id_cierre),
    CONSTRAINT fk_gastos_operacion_cierre
        FOREIGN KEY (id_cierre) REFERENCES cierres_diarios(id_cierre)
        ON DELETE RESTRICT
);

ALTER TABLE cierres_diarios
    ADD COLUMN IF NOT EXISTS total_gastos INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS total_neto INT NOT NULL DEFAULT 0;

ALTER TABLE usos_bano
    ADD COLUMN IF NOT EXISTS id_cierre INT NULL;

SET @idx_usos_bano_pendiente_exists := (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'usos_bano'
      AND index_name = 'idx_usos_bano_pendiente'
);
SET @sql := IF(
    @idx_usos_bano_pendiente_exists = 0,
    'ALTER TABLE usos_bano ADD INDEX idx_usos_bano_pendiente (id_cierre, fecha_hora)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_usos_bano_cierre_exists := (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'usos_bano'
      AND index_name = 'idx_usos_bano_cierre'
);
SET @sql := IF(
    @idx_usos_bano_cierre_exists = 0,
    'ALTER TABLE usos_bano ADD INDEX idx_usos_bano_cierre (id_cierre)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
