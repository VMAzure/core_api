# pdf.py
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
from io import BytesIO
from reportlab.lib.pagesizes import landscape, A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from fastapi_jwt_auth import AuthJWT

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

@router.post("/genera-offerta")
async def genera_offerta(
    offer: OfferPdfPage1,
    Authorize: AuthJWT = Depends()
):
    try:
        Authorize.jwt_required()

        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=landscape(A4))

        c.setFont("Helvetica-Bold", 22)
        c.drawString(50, 540, "Offerta NLT")

        c.setFont("Helvetica", 14)
        c.drawString(50, 500, f"Cliente: {offer.CustomerFirstName} {offer.CustomerLastName or ''} {offer.CustomerCompanyName or ''}")

        c.drawString(50, 470, f"Auto: {offer.Auto.Marca} {offer.Auto.Modello} - {offer.Auto.Versione} ({offer.Auto.Variante or '-'})")
        c.drawString(50, 450, f"Descrizione: {offer.Auto.DescrizioneVersione or ''}")
        c.drawString(50, 430, f"Note: {offer.Auto.Note or ''}")

        c.drawString(50, 390, "Dati Economici:")
        c.setFont("Helvetica", 12)
        c.drawString(70, 370, f"Durata: {offer.DatiEconomici.Durata} mesi")
        c.drawString(70, 355, f"Km Totali: {offer.DatiEconomici.KmTotali}")
        c.drawString(70, 340, f"Anticipo: €{offer.DatiEconomici.Anticipo:.2f}")
        c.drawString(70, 325, f"Canone Mensile: €{offer.DatiEconomici.Canone:.2f}")

        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, 290, "Servizi Inclusi:")
        c.setFont("Helvetica", 12)
        y = 270
        for s in offer.Servizi:
            c.drawString(70, y, f"- {s.Nome}: {s.Opzione}")
            y -= 15

        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, y - 10, "Documenti Richiesti:")
        c.setFont("Helvetica", 12)
        y -= 30
        for d in offer.DocumentiNecessari:
            c.drawString(70, y, f"- {d}")
            y -= 15

        c.showPage()
        c.save()

        buffer.seek(0)
        return StreamingResponse(buffer, media_type="application/pdf", headers={
            "Content-Disposition": "inline; filename=offerta.pdf"
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
