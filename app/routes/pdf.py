from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
from io import BytesIO
import requests
from weasyprint import HTML, CSS
from fastapi_jwt_auth import AuthJWT
from fastapi import Depends


router = APIRouter()

class AdminDealerData(BaseModel):
    Id: int
    Email: str
    FirstName: Optional[str]
    LastName: Optional[str]
    CompanyName: Optional[str]
    VatNumber: Optional[str]
    Address: Optional[str]
    PostalCode: Optional[str]
    City: Optional[str]
    SDICode: Optional[str]
    MobilePhone: Optional[str]
    LogoUrl: Optional[str]

class CarImageDetail(BaseModel):
    Url: str
    Color: str
    Angle: int

class Auto(BaseModel):
    Marca: str
    Modello: str
    Versione: str
    Variante: Optional[str]
    DescrizioneVersione: Optional[str]
    Note: Optional[str]

class Servizio(BaseModel):
    Nome: str
    Opzione: str

class DatiEconomici(BaseModel):
    Durata: int
    KmTotali: int
    Anticipo: float
    Canone: float

class OfferPdfPage1(BaseModel):
    CustomerFirstName: str
    CustomerLastName: Optional[str]
    CustomerCompanyName: Optional[str]
    CustomerIcon: Optional[str]
    TipoCliente: Optional[str] = "privato"
    DocumentiNecessari: List[str]
    CarImages: List[CarImageDetail]
    CarMainImageUrl: Optional[str]
    Auto: Auto
    Servizi: List[Servizio]
    DatiEconomici: DatiEconomici
    AdminInfo: AdminDealerData
    DealerInfo: Optional[AdminDealerData]
    NoteAuto: Optional[str]

@router.post("/pdf/genera-offerta")
async def genera_offerta(offer: OfferPdfPage1, Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()

    try:
        html_content = f"""
        <html>
        <head>
            <style>
                body {{ font-family: 'Segoe UI', sans-serif; padding: 40px; }}
                h1 {{ color: #00213b; }}
                h2 {{ color: #FF7100; margin-top: 30px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                td {{ padding: 6px 10px; border-bottom: 1px solid #ccc; }}
            </style>
        </head>
        <body>
            <h1>Offerta NLT</h1>
            <h2>Cliente</h2>
            <p>{offer.CustomerFirstName} {offer.CustomerLastName or ''} - {offer.CustomerCompanyName or ''}</p>

            <h2>Auto</h2>
            <p>{offer.Auto.Marca} {offer.Auto.Modello} - {offer.Auto.Versione} ({offer.Auto.Variante or '-'})</p>
            <p><strong>Descrizione:</strong> {offer.Auto.DescrizioneVersione or ''}</p>
            <p><strong>Note:</strong> {offer.Auto.Note or ''}</p>

            <h2>Dati Economici</h2>
            <table>
                <tr><td>Durata</td><td>{offer.DatiEconomici.Durata} mesi</td></tr>
                <tr><td>Km Totali</td><td>{offer.DatiEconomici.KmTotali}</td></tr>
                <tr><td>Anticipo</td><td>{offer.DatiEconomici.Anticipo:.2f} €</td></tr>
                <tr><td>Canone Mensile</td><td>{offer.DatiEconomici.Canone:.2f} €</td></tr>
            </table>

            <h2>Servizi Inclusi</h2>
            <ul>
                {''.join(f'<li>{s.Nome}: {s.Opzione}</li>' for s in offer.Servizi)}
            </ul>

            <h2>Documenti Richiesti</h2>
            <ul>
                {''.join(f'<li>{doc}</li>' for doc in offer.DocumentiNecessari)}
            </ul>
        </body>
        </html>
        """

        pdf_file = BytesIO()
        HTML(string=html_content).write_pdf(pdf_file)
        pdf_file.seek(0)

        return StreamingResponse(pdf_file, media_type="application/pdf", headers={
            "Content-Disposition": "inline; filename=offerta.pdf"
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
