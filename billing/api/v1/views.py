"""
Views for Insurance/Payer Master Data Management
"""
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from billing.models import InsurancePayer, Clearinghouse
from .serializers import InsurancePayerSerializer, ClearinghouseSerializer


class ClearinghouseViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing EDI Clearinghouses
    
    list: GET /api/billing/v1/clearinghouses/
    create: POST /api/billing/v1/clearinghouses/
    retrieve: GET /api/billing/v1/clearinghouses/{id}/
    update: PUT /api/billing/v1/clearinghouses/{id}/
    partial_update: PATCH /api/billing/v1/clearinghouses/{id}/
    destroy: DELETE /api/billing/v1/clearinghouses/{id}/
    """
    queryset = Clearinghouse.objects.all()
    serializer_class = ClearinghouseSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active', 'transmission_protocol', 'supports_837p', 'supports_837i', 'supports_835']
    search_fields = ['name', 'code', 'vendor_name']
    ordering_fields = ['name', 'created_at', 'updated_at']
    
    def get_queryset(self):
        """Filter by tenant in multi-tenant environment"""
        queryset = super().get_queryset()
        # In production, filter by current tenant
        # tenant = self.request.tenant  # Adjust based on your tenant middleware
        return queryset
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        """Get only active clearinghouses"""
        active_chs = self.get_queryset().filter(is_active=True)
        serializer = self.get_serializer(active_chs, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def by_protocol(self, request):
        """Filter clearinghouses by transmission protocol"""
        protocol = request.query_params.get('protocol', None)
        if protocol:
            chs = self.get_queryset().filter(transmission_protocol=protocol.upper(), is_active=True)
            serializer = self.get_serializer(chs, many=True)
            return Response(serializer.data)
        return Response({'error': 'Protocol parameter required'}, status=status.HTTP_400_BAD_REQUEST)


class InsurancePayerViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing Insurance Payers
    
    list: GET /api/billing/v1/payers/
    create: POST /api/billing/v1/payers/
    retrieve: GET /api/billing/v1/payers/{id}/
    update: PUT /api/billing/v1/payers/{id}/
    partial_update: PATCH /api/billing/v1/payers/{id}/
    destroy: DELETE /api/billing/v1/payers/{id}/
    """
    queryset = InsurancePayer.objects.all()
    serializer_class = InsurancePayerSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['payer_type', 'is_active', 'edi_enabled', 'claim_format', 'require_auth']
    search_fields = ['name', 'code', 'payer_id', 'short_name']
    ordering_fields = ['name', 'payer_type', 'created_at', 'updated_at']
    
    def get_queryset(self):
        """Filter by tenant in multi-tenant environment"""
        queryset = super().get_queryset()
        # In production, filter by current tenant
        # tenant = self.request.tenant
        return queryset
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        """Get only active payers"""
        active_payers = self.get_queryset().filter(is_active=True)
        serializer = self.get_serializer(active_payers, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def by_type(self, request):
        """Filter payers by type"""
        payer_type = request.query_params.get('type', None)
        if payer_type:
            payers = self.get_queryset().filter(payer_type=payer_type.upper(), is_active=True)
            serializer = self.get_serializer(payers, many=True)
            return Response(serializer.data)
        return Response({'error': 'Type parameter required'}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'])
    def edi_enabled(self, request):
        """Get payers with EDI enabled"""
        payers = self.get_queryset().filter(edi_enabled=True, is_active=True)
        serializer = self.get_serializer(payers, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def validation_rules(self, request, pk=None):
        """Get validation rules and requirements for a specific payer"""
        payer = self.get_object()
        rules = {
            'require_auth': payer.require_auth,
            'auth_required_cpt_codes': payer.auth_required_for_cpt.split(',') if payer.auth_required_for_cpt else [],
            'pos_restrictions': payer.place_of_service_restrictions.split(',') if payer.place_of_service_restrictions else [],
            'claim_format': payer.claim_format,
            'edi_enabled': payer.edi_enabled,
            'era_enabled': payer.era_enabled,
            'clearinghouse': str(payer.clearinghouse.name) if payer.clearinghouse else None,
        }
        return Response(rules)
