try:
    set
except NameError:
    from sets import Set as set

from django import template
from django.template import TOKEN_BLOCK
from django.http import Http404
from django.core.paginator import Paginator, InvalidPage
from django.conf import settings

register = template.Library()

DEFAULT_PAGINATION = getattr(settings, 'PAGINATION_DEFAULT_PAGINATION', 20)
DEFAULT_WINDOW = getattr(settings, 'PAGINATION_DEFAULT_WINDOW', 4)
DEFAULT_ORPHANS = getattr(settings, 'PAGINATION_DEFAULT_ORPHANS', 0)
INVALID_PAGE_RAISES_404 = getattr(settings,
    'PAGINATION_INVALID_PAGE_RAISES_404', False)
DISPLAY_PAGE_LINKS = getattr(settings, 'PAGINATION_DISPLAY_PAGE_LINKS', True)
PREVIOUS_LINK_DECORATOR = getattr(settings, 'PAGINATION_PREVIOUS_LINK_DECORATOR', "&lsaquo;&lsaquo; ")
NEXT_LINK_DECORATOR = getattr(settings, 'PAGINATION_NEXT_LINK_DECORATOR', " &rsaquo;&rsaquo;")
DISPLAY_DISABLED_PREVIOUS_LINK = getattr(settings, 'PAGINATION_DISPLAY_DISABLED_PREVIOUS_LINK', False)
DISPLAY_DISABLED_NEXT_LINK = getattr(settings, 'PAGINATION_DISPLAY_DISABLED_NEXT_LINK', False)

def do_autopaginate(parser, token):
    """
    Splits the arguments to the autopaginate tag and formats them correctly.

    Syntax is:

        autopaginate SOMETHING [PAGINATE_BY] [ORPHANS] [as NAME]
    """
    # Check whether there are any other autopaginations are later in this template
    expr = lambda obj: (obj.token_type == TOKEN_BLOCK and \
        len(obj.split_contents()) > 0 and obj.split_contents()[0] == "autopaginate")
    multiple_paginations = len(filter(expr, parser.tokens)) > 0

    i = iter(token.split_contents())
    paginate_by = None
    queryset_var = None
    context_var = None
    orphans = None
    word = None
    try:
        word = i.next()
        assert word == "autopaginate"
        queryset_var = i.next()
        word = i.next()
        if word != "as":
            paginate_by = word
            try:
                paginate_by = int(paginate_by)
            except ValueError:
                pass
            word = i.next()
        if word != "as":
            orphans = word
            try:
                orphans = int(orphans)
            except ValueError:
                pass
            word = i.next()
        assert word == "as"
        context_var = i.next()
    except StopIteration:
        pass
    if queryset_var is None:
        raise template.TemplateSyntaxError(
            "Invalid syntax. Proper usage of this tag is: "
            "{%% autopaginate QUERYSET [PAGINATE_BY] [ORPHANS]"
            " [as CONTEXT_VAR_NAME] %%}"
        )
    return AutoPaginateNode(queryset_var, multiple_paginations, paginate_by, orphans, context_var)


class AutoPaginateNode(template.Node):
    """
    Emits the required objects to allow for Digg-style pagination.
    
    First, it looks in the current context for the variable specified, and using
    that object, it emits a simple ``Paginator`` and the current page object 
    into the context names ``paginator`` and ``page_obj``, respectively.
    
    It will then replace the variable specified with only the objects for the
    current page.
    
    .. note::
        
        It is recommended to use *{% paginate %}* after using the autopaginate
        tag.  If you choose not to use *{% paginate %}*, make sure to display the
        list of available pages, or else the application may seem to be buggy.
    """
    def __init__(self, queryset_var,  multiple_paginations, paginate_by=None,
                 orphans=None, context_var=None):
        if paginate_by is None:
            paginate_by = DEFAULT_PAGINATION
        if orphans is None:
            orphans = DEFAULT_ORPHANS
        self.queryset_var = template.Variable(queryset_var)
        if isinstance(paginate_by, int):
            self.paginate_by = paginate_by
        else:
            self.paginate_by = template.Variable(paginate_by)
        if isinstance(orphans, int):
            self.orphans = orphans
        else:
            self.orphans = template.Variable(orphans)
        self.context_var = context_var
        self.multiple_paginations = multiple_paginations

    def render(self, context):
        if self.multiple_paginations or context.has_key('paginator'):
            page_suffix = '_%s' % self.queryset_var
        else:
            page_suffix = ''
        
        key = self.queryset_var.var
        value = self.queryset_var.resolve(context)
        if isinstance(self.paginate_by, int):
            paginate_by = self.paginate_by
        else:
            paginate_by = self.paginate_by.resolve(context)
        if isinstance(self.orphans, int):
            orphans = self.orphans
        else:
            orphans = self.orphans.resolve(context)
        paginator = Paginator(value, paginate_by, orphans)
        try:
            page_obj = paginator.page(context['request'].page(page_suffix))
        except InvalidPage:
            if INVALID_PAGE_RAISES_404:
                raise Http404('Invalid page requested.  If DEBUG were set to ' +
                    'False, an HTTP 404 page would have been shown instead.')
            context[key] = []
            context['invalid_page'] = True
            return u''
        if self.context_var is not None:
            context[self.context_var] = page_obj.object_list
        else:
            context[key] = page_obj.object_list
        context['paginator'] = paginator
        context['page_obj'] = page_obj
        context['page_suffix'] = page_suffix
        return u''


def paginate(context, window=DEFAULT_WINDOW):
    """
    Renders the ``pagination/pagination.html`` template, resulting in a
    Digg-like display of the available pages, given the current page.  If there
    are too many pages to be displayed before and after the current page, then
    elipses will be used to indicate the undisplayed gap between page numbers.
    
    Requires one argument, ``context``, which should be a dictionary-like data
    structure and must contain the following keys:
    
    ``paginator``
        A ``Paginator`` or ``QuerySetPaginator`` object.
    
    ``page_obj``
        This should be the result of calling the page method on the 
        aforementioned ``Paginator`` or ``QuerySetPaginator`` object, given
        the current page.
    
    This same ``context`` dictionary-like data structure may also include:
    
    ``getvars``
        A dictionary of all of the **GET** parameters in the current request.
        This is useful to maintain certain types of state, even when requesting
        a different page.
    
    ``pagination_template``
        A custom template to include in place of the default ``pagination.html`` 
        contents.
        
    """
    try:
        paginator = context['paginator']
        page_obj = context['page_obj']
        page_suffix = context.get('page_suffix', '')
        page_range = paginator.page_range
        pagination_template = context.get('pagination_template', 'pagination/default.html')
        # Calculate the record range in the current page for display.
        records = {'first': 1 + (page_obj.number - 1) * paginator.per_page}
        records['last'] = records['first'] + paginator.per_page - 1
        if records['last'] + paginator.orphans >= paginator.count:
            records['last'] = paginator.count
        # First and last are simply the first *n* pages and the last *n* pages,
        # where *n* is the current window size.
        first = set(page_range[:window])
        last = set(page_range[-window:])
        # Now we look around our current page, making sure that we don't wrap
        # around.
        current_start = page_obj.number-1-window
        if current_start < 0:
            current_start = 0
        current_end = page_obj.number-1+window
        if current_end < 0:
            current_end = 0
        current = set(page_range[current_start:current_end])
        pages = []
        # If there's no overlap between the first set of pages and the current
        # set of pages, then there's a possible need for elusion.
        if len(first.intersection(current)) == 0:
            first_list = list(first)
            first_list.sort()
            second_list = list(current)
            second_list.sort()
            pages.extend(first_list)
            diff = second_list[0] - first_list[-1]
            # If there is a gap of two, between the last page of the first
            # set and the first page of the current set, then we're missing a
            # page.
            if diff == 2:
                pages.append(second_list[0] - 1)
            # If the difference is just one, then there's nothing to be done,
            # as the pages need no elusion and are correct.
            elif diff == 1:
                pass
            # Otherwise, there's a bigger gap which needs to be signaled for
            # elusion, by pushing a None value to the page list.
            else:
                pages.append(None)
            pages.extend(second_list)
        else:
            unioned = list(first.union(current))
            unioned.sort()
            pages.extend(unioned)
        # If there's no overlap between the current set of pages and the last
        # set of pages, then there's a possible need for elusion.
        if len(current.intersection(last)) == 0:
            second_list = list(last)
            second_list.sort()
            diff = second_list[0] - pages[-1]
            # If there is a gap of two, between the last page of the current
            # set and the first page of the last set, then we're missing a 
            # page.
            if diff == 2:
                pages.append(second_list[0] - 1)
            # If the difference is just one, then there's nothing to be done,
            # as the pages need no elusion and are correct.
            elif diff == 1:
                pass
            # Otherwise, there's a bigger gap which needs to be signaled for
            # elusion, by pushing a None value to the page list.
            else:
                pages.append(None)
            pages.extend(second_list)
        else:
            differenced = list(last.difference(current))
            differenced.sort()
            pages.extend(differenced)
        to_return = {
            'MEDIA_URL': settings.MEDIA_URL,
            'STATIC_URL': getattr(settings, "STATIC_URL", None),
            'pages': pages,
            'page_obj': page_obj,
            'paginator': paginator,
            'is_paginated': paginator.count > paginator.per_page,
            'page_suffix': page_suffix,
            'display_page_links': DISPLAY_PAGE_LINKS,
            'display_disabled_previous_link': DISPLAY_DISABLED_PREVIOUS_LINK,
            'display_disabled_next_link': DISPLAY_DISABLED_NEXT_LINK,
            'previous_link_decorator': PREVIOUS_LINK_DECORATOR,
            'next_link_decorator': NEXT_LINK_DECORATOR,
            'pagination_template': pagination_template,
        }
        if 'request' in context:
            getvars = context['request'].GET.copy()
            if 'page%s' % page_suffix in getvars:
                del getvars['page%s' % page_suffix]
            if len(getvars.keys()) > 0:
                to_return['getvars'] = "&%s" % getvars.urlencode()
            else:
                to_return['getvars'] = ''
        return to_return
    except (KeyError, AttributeError):
        return {}


register.inclusion_tag(
    'pagination/pagination.html', takes_context=True)(paginate)

register.tag('autopaginate', do_autopaginate)
