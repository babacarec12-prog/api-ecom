from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("commerce", "0001_commerce_state")]
    operations = [
        migrations.AlterModelTable(name="cart", table="carts"),
        migrations.AlterModelTable(name="productselection", table="product_selections"),
        migrations.AlterModelTable(name="conversationstate", table="conversation_states"),
        migrations.AlterModelTable(name="processedrequest", table="processed_requests"),
        migrations.AlterModelTable(name="userorder", table="user_orders"),
        migrations.AlterModelTable(name="humantransfer", table="human_transfers"),
        migrations.AlterModelTable(name="shoppolicy", table="shop_policies"),
    ]
