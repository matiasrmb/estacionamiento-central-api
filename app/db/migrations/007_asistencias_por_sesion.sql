ALTER TABLE asistencias
    ADD COLUMN IF NOT EXISTS device_id VARCHAR(128) NULL,
    ADD COLUMN IF NOT EXISTS session_id VARCHAR(64) NULL;

SET @idx_asistencias_sesion_activa_exists := (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'asistencias'
      AND index_name = 'idx_asistencias_sesion_activa'
);
SET @sql := IF(
    @idx_asistencias_sesion_activa_exists = 0,
    'ALTER TABLE asistencias ADD INDEX idx_asistencias_sesion_activa (usuario, session_id, hora_salida)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
