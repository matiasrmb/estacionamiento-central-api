ALTER TABLE operaciones_servicio
    ADD COLUMN IF NOT EXISTS cerrado BOOLEAN NOT NULL DEFAULT FALSE;

SET @idx_operaciones_servicio_cierre_exists := (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'operaciones_servicio'
      AND index_name = 'idx_operaciones_servicio_cierre'
);
SET @sql := IF(
    @idx_operaciones_servicio_cierre_exists = 0,
    'ALTER TABLE operaciones_servicio ADD INDEX idx_operaciones_servicio_cierre (cerrado, estado, fecha_hora_fin)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

ALTER TABLE cierres_diarios
    ADD COLUMN IF NOT EXISTS total_lavados_solos INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS total_lavados_solos_monto INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS total_general INT NOT NULL DEFAULT 0;
