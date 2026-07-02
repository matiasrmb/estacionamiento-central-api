CREATE TABLE IF NOT EXISTS operaciones_servicio (
    id_operacion_servicio INT AUTO_INCREMENT PRIMARY KEY,
    patente VARCHAR(10) NOT NULL,
    id_tipo_vehiculo_lavado INT NULL,
    tipo_vehiculo_lavado_snapshot VARCHAR(80) NOT NULL,
    valor_lavado_snapshot INT NOT NULL,
    fecha_hora_inicio DATETIME NOT NULL,
    fecha_hora_fin DATETIME NULL,
    duracion_minutos INT NULL,
    usuario_inicio VARCHAR(50) NOT NULL,
    usuario_fin VARCHAR(50) NULL,
    estado ENUM('ACTIVO', 'FINALIZADO_COBRADO', 'CONVERTIDO_ESTADIA') NOT NULL DEFAULT 'ACTIVO',
    id_ingreso_generado INT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_operaciones_servicio_estado_fecha (estado, fecha_hora_inicio),
    INDEX idx_operaciones_servicio_patente (patente),
    INDEX idx_operaciones_servicio_ingreso_generado (id_ingreso_generado)
);
