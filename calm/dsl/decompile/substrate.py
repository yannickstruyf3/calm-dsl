from calm.dsl.decompile.render import render_template
from calm.dsl.builtins import SubstrateType, BlueprintType
from tests.next_demo.test_next_demo import NextDslBlueprint
from calm.dsl.decompile.ref import render_ref_template
from calm.dsl.decompile.variable import render_variable_template
from calm.dsl.decompile.action import render_action_template


def render_substrate_template(cls):

    if not isinstance(cls, SubstrateType):
        raise TypeError("{} is not of type {}".format(cls, SubstrateType))
    
    user_attrs = cls.get_user_attrs()
    user_attrs["name"] = cls.__name__
    user_attrs["description"] = cls.__doc__
    user_attrs["readiness_probe"] = cls.readiness_probe.compile(cls)

    provider_spec = cls.provider_spec
    # TODO create a file for storing provider_spe

    text = render_template(schema_file="substrate.py.jinja2", obj=user_attrs)
    return text.strip()


bp_dict = NextDslBlueprint.get_dict()
bp_cls = BlueprintType.decompile(bp_dict)

print(render_substrate_template(bp_cls.substrates[0]))
