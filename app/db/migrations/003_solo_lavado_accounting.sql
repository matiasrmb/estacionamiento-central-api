ALTER TABLE operaciones_servicio
    ADD COLUMN IF NOT EXISTS cerrado BOOLEAN NOT NULL DEFAULT FALSE,
    ADD INDEX IF NOT EXISTS idx_operaciones_servicio_cierre (cerrado, estado, fecha_hora_fin);

ALTER TABLE cierres_diarios
    ADD COLUMN IF NOT EXISTS total_lavados_solos INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS total_lavados_solos_monto INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS total_general INT NOT NULL DEFAULT 0;
