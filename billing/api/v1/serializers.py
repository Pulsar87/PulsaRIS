"""
Serializers for Insurance/Payer Master Data Management
"""
from rest_framework import serializers
from billing.models import InsurancePayer, Clearinghouse


class ClearinghouseSerializer(serializers.ModelSerializer):
    """Serializer for Clearinghouse model"""
    
    class Meta:
        model = Clearinghouse
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']


class InsurancePayerSerializer(serializers.ModelSerializer):
    """Serializer for InsurancePayer model with nested Clearinghouse"""
    clearinghouse_details = ClearinghouseSerializer(source='clearinghouse', read_only=True)
    clearinghouse_id = serializers.PrimaryKeyRelatedField(
        queryset=Clearinghouse.objects.all(),
        source='clearinghouse',
        required=False,
        allow_null=True,
        write_only=True
    )
    
    class Meta:
        model = InsurancePayer
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate_code(self, value):
        """Validate payer code is uppercase and alphanumeric"""
        if value:
            return value.upper().replace(' ', '_')
        return value
    
    def validate_payer_id(self, value):
        """Validate payer ID format"""
        if value:
            return value.strip().upper()
        return value
