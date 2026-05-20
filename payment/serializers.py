from rest_framework import serializers


class AddValueSerializer(serializers.Serializer):
    payment_method_id = serializers.CharField(required=True)
    amount = serializers.DecimalField(max_digits=5, decimal_places=2, required=True)

    def validate_amount(self, value):
        if value < 5:
            msg = "Amount must be no less than $5.00"
            raise serializers.ValidationError(msg)
        if value > 200:
            msg = "Amount must be less than $200"
            raise serializers.ValidationError(msg)
        return value


class AddValueHistorySerializer(serializers.Serializer):
    # Use a nice date format for the user
    date = serializers.DateTimeField(format="%A, %B %d, %Y %I:%M%p")  # type: ignore

    amount = serializers.DecimalField(max_digits=5, decimal_places=2)
    status = serializers.CharField()


class StripeCustomerPortalRequestSerializer(serializers.Serializer):
    return_url = serializers.URLField(required=False)


class StripeCheckoutRequestSerializer(serializers.Serializer):
    success_url = serializers.URLField(required=False)
    cancel_url = serializers.URLField(required=False)


class URLResponseSerializer(serializers.Serializer):
    url = serializers.URLField()


class PaymentMessageResponseSerializer(serializers.Serializer):
    message = serializers.CharField()


class PaymentErrorResponseSerializer(serializers.Serializer):
    error = serializers.CharField()


class WebhookPayloadSerializer(serializers.Serializer):
    signedPayload = serializers.CharField(required=False)  # noqa: N815


class AppleSubscriptionRequestSerializer(serializers.Serializer):
    transaction_id = serializers.CharField()
