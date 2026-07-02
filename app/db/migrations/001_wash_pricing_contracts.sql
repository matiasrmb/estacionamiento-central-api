CREATE TABLE IF NOT EXISTS tipos_lavado (
    id_tipo_lavado INT AUTO_INCREMENT PRIMARY KEY,
    codigo VARCHAR(50) NOT NULL UNIQUE,
    nombre VARCHAR(80) NOT NULL,
    activo TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tipos_vehiculo_lavado (
    id_tipo_vehiculo_lavado INT AUTO_INCREMENT PRIMARY KEY,
    codigo VARCHAR(50) NOT NULL UNIQUE,
    nombre VARCHAR(80) NOT NULL,
    valor_lavado INT NOT NULL,
    activo TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

ALTER TABLE lavados
    ADD COLUMN IF NOT EXISTS id_tipo_vehiculo_lavado INT NULL,
    ADD COLUMN IF NOT EXISTS tipo_vehiculo_lavado_snapshot VARCHAR(80) DEFAULT NULL;

INSERT INTO tipos_lavado (codigo, nombre, activo) VALUES
('lavado_general', 'Lavado', 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), activo = VALUES(activo);

INSERT INTO tipos_vehiculo_lavado (codigo, nombre, valor_lavado, activo) VALUES
('lavado_citycar', 'CityCar', 5000, 1),
('lavado_suv', 'SUV', 8000, 1),
('lavado_camioneta', 'Camioneta', 10000, 1),
('lavado_furgon', 'Furgon', 15000, 1),
('lavado_minibus', 'Mini bus o vehiculos grandes', 25000, 1)
ON DUPLICATE KEY UPDATE
    nombre = VALUES(nombre),
    valor_lavado = VALUES(valor_lavado),
    activo = VALUES(activo);
