import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.api.v1.endpoints import ingresos
from app.repositories.ingresos_repo import IngresoWaitingError


class MarcarEsperaEndpointTests(unittest.TestCase):
    def test_marks_an_open_ingreso_as_waiting(self):
        with patch.object(ingresos, "marcar_ingreso_en_espera") as mark:
            result = ingresos.marcar_en_espera(15, {"sub": "operador"})

        self.assertEqual(result, {"ok": True, "id_ingreso": 15, "en_espera": True})
        mark.assert_called_once_with(15)

    def test_maps_not_found_and_terminal_states(self):
        for code, expected_status in (
            ("INGRESO_NOT_FOUND", 404),
            ("INGRESO_CLOSED", 409),
            ("INGRESO_DELETED", 409),
            ("INGRESO_ALREADY_WAITING", 409),
            ("INGRESO_NOT_ACTIVE", 409),
        ):
            with self.subTest(code=code), patch.object(
                ingresos, "marcar_ingreso_en_espera", side_effect=IngresoWaitingError(code)
            ):
                with self.assertRaises(HTTPException) as raised:
                    ingresos.marcar_en_espera(15, {"sub": "operador"})
            self.assertEqual(raised.exception.status_code, expected_status)
            self.assertEqual(raised.exception.detail["error"]["code"], code)


if __name__ == "__main__":
    unittest.main()
