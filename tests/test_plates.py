import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.api.v1.endpoints import ingresos, mensuales, solo_lavados
from app.core.plates import is_valid_plate, normalize_plate


class PlateTests(unittest.TestCase):
    def test_accepts_all_supported_formats(self):
        for plate in ("ABCD12", "ABC12", "AB123CD", "ABC123"):
            with self.subTest(plate=plate):
                self.assertTrue(is_valid_plate(plate))

    def test_normalizes_lowercase_spaces_and_hyphens_only(self):
        self.assertEqual(normalize_plate("ab-cd 12"), "ABCD12")
        self.assertEqual(normalize_plate("ab-123 cd"), "AB123CD")

    def test_rejects_special_and_accented_characters(self):
        for plate in ("AB{CD12", "AB[CD12", "ABCD1'2", "ÁBCD12", "ABCD.12"):
            with self.subTest(plate=plate):
                self.assertFalse(is_valid_plate(plate))

    def test_write_endpoints_pass_the_normalized_plate(self):
        with patch.object(ingresos, "create_ingreso_with_required_pc_pdf_job", return_value={"id_ingreso": 1, "pc_job_id": 2}) as create, patch.object(mensuales, "upsert_mensual", return_value=3) as upsert, patch.object(solo_lavados, "repo_iniciar_solo_lavado", return_value={}) as wash:
            ingresos.registrar_ingreso(ingresos.IngresoRequest(patente="ab-cd 12"), user={"sub": "operator"})
            mensuales.crear_mensual(mensuales.MensualIn(patente="ab-123 cd"))
            solo_lavados.iniciar_solo_lavado(solo_lavados.SoloLavadoInicioIn(patente="ab c12", id_tipo_vehiculo_lavado=1), user={"sub": "operator"})

        self.assertEqual(create.call_args.kwargs["patente"], "ABCD12")
        upsert.assert_called_once_with("AB123CD", None, None, None)
        wash.assert_called_once_with("ABC12", 1, "operator")

    def test_write_endpoints_reject_invalid_special_characters(self):
        with self.assertRaises(HTTPException) as raised:
            ingresos.registrar_ingreso(ingresos.IngresoRequest(patente="AB{CD12"), user={"sub": "operator"})

        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
