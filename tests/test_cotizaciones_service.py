import unittest

from app.services.cotizaciones import (
    cotizar_combinada,
    cotizar_estadia,
    cotizar_lavado,
    cotizar_mensualidad,
)


class CotizacionesServiceTests(unittest.TestCase):
    def test_cotizar_estadia_ignora_tamano_vehiculo(self):
        citycar = cotizar_estadia(90, 2500, tamano_vehiculo="citycar")
        camioneta = cotizar_estadia(90, 2500, tamano_vehiculo="camioneta")

        self.assertEqual(citycar["monto"], 2500)
        self.assertEqual(camioneta["monto"], 2500)
        self.assertEqual(citycar, camioneta)

    def test_cotizar_mensualidad_requiere_monto_faltante(self):
        cotizacion = cotizar_mensualidad([
            {"patente": "AAA111", "monto_mensual": None},
        ])

        self.assertTrue(cotizacion["requiere_monto"])
        self.assertIsNone(cotizacion["vehiculos"][0]["monto_mensual"])
        self.assertIsNone(cotizacion["vehiculos"][0]["costo_diario"])
        self.assertEqual(cotizacion["total_mensual"], 0)

    def test_cotizar_mensualidad_suma_varios_vehiculos(self):
        cotizacion = cotizar_mensualidad([
            {"patente": "AAA111", "monto_mensual": 60000},
            {"patente": "BBB222", "monto_configurado": 30000},
        ])

        self.assertFalse(cotizacion["requiere_monto"])
        self.assertEqual(cotizacion["total_mensual"], 90000)
        self.assertEqual(cotizacion["total_diario"], 3000)
        self.assertEqual(
            [vehiculo["costo_diario"] for vehiculo in cotizacion["vehiculos"]],
            [2000, 1000],
        )

    def test_cotizar_combinada_suma_previews_sin_efectos(self):
        estadia = cotizar_estadia(60, 2000, tamano_vehiculo="suv")
        lavado = cotizar_lavado("SUV", 8000)
        mensualidad = cotizar_mensualidad([{"patente": "AAA111", "monto_mensual": 30000}])

        cotizacion = cotizar_combinada(estadia, lavado, mensualidad)

        self.assertEqual(cotizacion["total"], 40000)
        self.assertEqual([item["tipo"] for item in cotizacion["items"]], ["estadia", "lavado", "mensualidad"])


if __name__ == "__main__":
    unittest.main()
